import click
import subprocess
from os import path, makedirs


DS_VERSION = '2018.04.18'
S3_HTTP_PREFIX = 'https://s3-us-west-2.amazonaws.com/pinafore-us-west-2/qanta-jmlr-datasets/'
QANTA_MAPPED_DATASET_PATH = f'qanta.mapped.{DS_VERSION}.json'
QANTA_TRAIN_DATASET_PATH = f'qanta.train.{DS_VERSION}.json'
QANTA_DEV_DATASET_PATH = f'qanta.dev.{DS_VERSION}.json'
QANTA_TEST_DATASET_PATH = f'qanta.test.{DS_VERSION}.json'

FILES = [
    QANTA_MAPPED_DATASET_PATH,
    QANTA_TRAIN_DATASET_PATH,
    QANTA_DEV_DATASET_PATH,
    QANTA_TEST_DATASET_PATH
]

from typing import List, Dict, Iterable, Optional, Tuple, NamedTuple
import os
import json

GUESSER_TRAIN_FOLD = 'guesstrain'
BUZZER_TRAIN_FOLD = 'buzztrain'
TRAIN_FOLDS = {GUESSER_TRAIN_FOLD, BUZZER_TRAIN_FOLD}

# Guesser and buzzers produce reports on these for cross validation
GUESSER_DEV_FOLD = 'guessdev'
BUZZER_DEV_FOLD = 'buzzdev'
DEV_FOLDS = {GUESSER_DEV_FOLD, BUZZER_DEV_FOLD}

# System-wide cross validation and testing
GUESSER_TEST_FOLD = 'guesstest'
BUZZER_TEST_FOLD = 'buzztest'


class Question(NamedTuple):
    qanta_id: int
    text: str
    first_sentence: str
    tokenizations: List[Tuple[int, int]]
    answer: str
    page: Optional[str]
    fold: str
    gameplay: bool
    category: Optional[str]
    subcategory: Optional[str]
    tournament: str
    difficulty: str
    year: int
    proto_id: Optional[int]
    qdb_id: Optional[int]
    dataset: str

    def to_json(self) -> str:
        return json.dumps(self._asdict())

    @classmethod
    def from_json(cls, json_text):
        return cls(**json.loads(json_text))

    @classmethod
    def from_dict(cls, dict_question):
        return cls(**dict_question)

    def to_dict(self) -> Dict:
        return self._asdict()

    @property
    def sentences(self) -> List[str]:
        """
        Returns a list of sentences in the question using preprocessed spacy 2.0.11
        """
        return [self.text[start:end] for start, end in self.tokenizations]

    def runs(self, char_skip: int) -> Tuple[List[str], List[int]]:
        """
        Returns runs of the question based on skipping char_skip characters at a time. Also returns the indices used

        q: name this first united states president.
        runs with char_skip=10:
        ['name this ',
         'name this first unit',
         'name this first united state p',
         'name this first united state president.']

        :param char_skip: Number of characters to skip each time
        """
        char_indices = list(range(char_skip, len(self.text) + char_skip, char_skip))
        return [self.text[:i] for i in char_indices], char_indices


class QantaDatabase:
    def __init__(self, dataset_path=os.path.join('qanta-codalab/data/', QANTA_MAPPED_DATASET_PATH), category=None):
        with open(dataset_path) as f:
            self.dataset = json.load(f)

        self.version = self.dataset['version']
        self.raw_questions = self.dataset['questions']
        self.all_questions = [Question(**q) for q in self.raw_questions]
        if category is not None:
            self.mapped_questions = [q for q in self.all_questions if q.page is not None and q.category in category]
        else:
            self.mapped_questions = [q for q in self.all_questions if q.page is not None]

        self.train_questions = [q for q in self.mapped_questions if q.fold in TRAIN_FOLDS]
        self.guess_train_questions = [q for q in self.train_questions if q.fold == GUESSER_TRAIN_FOLD]
        self.buzz_train_questions = [q for q in self.train_questions if q.fold == BUZZER_TRAIN_FOLD]

        self.dev_questions = [q for q in self.mapped_questions if q.fold in DEV_FOLDS]
        self.guess_dev_questions = [q for q in self.dev_questions if q.fold == GUESSER_DEV_FOLD]
        self.buzz_dev_questions = [q for q in self.dev_questions if q.fold == BUZZER_DEV_FOLD]

        self.buzz_test_questions = [q for q in self.mapped_questions if q.fold == BUZZER_TEST_FOLD]
        self.guess_test_questions = [q for q in self.mapped_questions if q.fold == GUESSER_TEST_FOLD]

    def by_fold(self):
        return {
            GUESSER_TRAIN_FOLD: self.guess_train_questions,
            GUESSER_DEV_FOLD: self.guess_dev_questions,
            BUZZER_TRAIN_FOLD: self.buzz_train_questions,
            BUZZER_DEV_FOLD: self.buzz_dev_questions,
            BUZZER_TEST_FOLD: self.buzz_test_questions,
            GUESSER_TEST_FOLD: self.guess_test_questions
        }

class QuizBowlDataset:
    def __init__(self, *, guesser_train=False, buzzer_train=False, category=None, predict_category=False):
        """
        Initialize a new quiz bowl data set
        """
        super().__init__()
        if not guesser_train and not buzzer_train:
            raise ValueError('Requesting a dataset which produces neither guesser or buzzer training data is invalid')

        if guesser_train and buzzer_train:
            print('Using QuizBowlDataset with guesser and buzzer training data, make sure you know what you are doing!')
        self.db = QantaDatabase(category=category)
        self.guesser_train = guesser_train
        self.buzzer_train = buzzer_train
        self.predict_category = predict_category

    def training_data(self):
        training_examples = []
        training_pages = []
        questions = []
        if self.guesser_train:
            questions.extend(self.db.guess_train_questions)
        if self.buzzer_train:
            questions.extend(self.db.buzz_train_questions)

        for q in questions:
            training_examples.append(q.sentences)
            if self.predict_category:
                training_pages.append(q.category)
            else:
                training_pages.append(q.page)

        return training_examples, training_pages, None

    def questions_by_fold(self):
        return {
            GUESSER_TRAIN_FOLD: self.db.guess_train_questions,
            GUESSER_DEV_FOLD: self.db.guess_dev_questions,
            BUZZER_TRAIN_FOLD: self.db.buzz_train_questions,
            BUZZER_DEV_FOLD: self.db.buzz_dev_questions,
            BUZZER_TEST_FOLD: self.db.buzz_test_questions,
            GUESSER_TEST_FOLD: self.db.guess_test_questions
        }

    def questions_in_folds(self, folds):
        by_fold = self.questions_by_fold()
        questions = []
        for fold in folds:
            questions.extend(by_fold[fold])
        return questions
