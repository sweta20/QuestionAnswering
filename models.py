import torch.nn as nn
import numpy as np
from torch.nn import functional as F
from torch.autograd import Variable
from torch.optim import Adam, lr_scheduler
from allennlp.modules.elmo import Elmo, batch_to_ids
import torch

ELMO_OPTIONS_FILE = "https://s3-us-west-2.amazonaws.com/allennlp/models/elmo/2x4096_512_2048cnn_2xhighway/elmo_2x4096_512_2048cnn_2xhighway_options.json"
ELMO_WEIGHTS_FILE = "https://s3-us-west-2.amazonaws.com/allennlp/models/elmo/2x4096_512_2048cnn_2xhighway/elmo_2x4096_512_2048cnn_2xhighway_weights.hdf5"
ELMO_DIM = 1024


class DanEncoder(nn.Module):
    def __init__(self, embedding_dim, n_hidden_layers, n_hidden_units, dropout_prob):
        super(DanEncoder, self).__init__()
        encoder_layers = []
        for i in range(n_hidden_layers):
            if i == 0:
                input_dim = embedding_dim
            else:
                input_dim = n_hidden_units

            encoder_layers.extend([
                nn.Linear(input_dim, n_hidden_units),
                nn.BatchNorm1d(n_hidden_units),
                nn.ELU(),
                nn.Dropout(dropout_prob),
            ])
        self.encoder = nn.Sequential(*encoder_layers)

    def forward(self, x_array):
        return self.encoder(x_array)


class DanModel(nn.Module):
    def __init__(self, n_classes, text_vocab_size,
                 init_embeddings=True, emb_dim=300,
                 n_hidden_units=1000, n_hidden_layers=1, nn_dropout=.265,
                 pooling='avg'):
        super(DanModel, self).__init__()
        self.emb_dim = emb_dim
        self.n_classes = n_classes
        self.n_hidden_units = n_hidden_units
        self.n_hidden_layers = n_hidden_layers
        self.nn_dropout = nn_dropout
        self.pooling = pooling
        self.text_vocab_size = text_vocab_size
        self.text_embeddings = nn.Embedding(self.text_vocab_size, emb_dim)
        self.dropout = nn.Dropout(nn_dropout)
        self.encoder = DanEncoder(emb_dim, self.n_hidden_layers, self.n_hidden_units, self.nn_dropout)
        self.classifier = nn.Sequential(
            nn.Linear(self.n_hidden_units, n_classes),
            nn.BatchNorm1d(n_classes),
            nn.Dropout(self.nn_dropout)
        )

    def _pool(self, embed, lengths, batch_size):
        if self.pooling == 'avg':
            return embed.sum(1) / lengths.view(batch_size, -1)
        elif self.pooling == 'max':
            emb_max, _ = torch.max(embed, 1)
            return emb_max
        else:
            raise ValueError(f'Unsupported pooling type f{self.pooling}, only avg and max are supported')

    def forward(self, text_input, text_len):
        """
        :param input_: [batch_size, seq_len] of word indices
        :param lengths: Length of each example
        :param qanta_ids: QB qanta_id if a qb question, otherwise -1 for wikipedia, used to get domain as source/target
        :return:
        """
        embed = self.text_embeddings(text_input)
        embed = self._pool(embed, text_len.float(), text_input.size()[0])
        embed = self.dropout(embed)
        encoded = self.encoder(embed)
        return self.classifier(encoded)


class ElmoModel(nn.Module):
    def __init__(self, n_classes, dropout=.5):
        super().__init__()
        self.dropout = dropout
        # This turns off gradient updates for the elmo model, but still leaves scalar mixture
        # parameters as tunable, provided that references to the scalar mixtures are extracted
        # and plugged into the optimizer
        self.elmo = Elmo(ELMO_OPTIONS_FILE, ELMO_WEIGHTS_FILE, 2, dropout=dropout, requires_grad=False)
        self.classifier = nn.Sequential(
            nn.Linear(2 * ELMO_DIM, n_classes),
            nn.BatchNorm1d(n_classes),
            nn.Dropout(dropout)
        )

    def forward(self, questions, lengths):
        embeddings = self.elmo(questions)
        layer_0 = embeddings['elmo_representations'][0]
        layer_0 = layer_0.sum(1) / lengths
        layer_1 = embeddings['elmo_representations'][1]
        layer_1 = layer_1.sum(1) / lengths
        layer = torch.cat([layer_0, layer_1], 1)
        return self.classifier(layer)

class ElmoDANModel(nn.Module):
    def __init__(self, n_classes, n_hidden_units, dropout=.25):
        super().__init__()
        self.dropout = dropout
        # This turns off gradient updates for the elmo model, but still leaves scalar mixture
        # parameters as tunable, provided that references to the scalar mixtures are extracted
        # and plugged into the optimizer
        self.elmo = Elmo(ELMO_OPTIONS_FILE, ELMO_WEIGHTS_FILE, 2, dropout=dropout, requires_grad=False)
        self.classifier = nn.Sequential(
            nn.Linear(2 * ELMO_DIM, n_hidden_units),
            nn.ReLU(),
            nn.Linear(n_hidden_units, n_classes),
            nn.BatchNorm1d(n_classes),
            nn.Dropout(dropout)
        )

    def forward(self, questions, lengths):
        embeddings = self.elmo(questions)
        layer_0 = embeddings['elmo_representations'][0]
        layer_0 = layer_0.sum(1) / lengths
        layer_1 = embeddings['elmo_representations'][1]
        layer_1 = layer_1.sum(1) / lengths
        layer = torch.cat([layer_0, layer_1], 1)
        return self.classifier(layer)
