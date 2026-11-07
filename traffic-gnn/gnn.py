"""Day 3: a small spatio-temporal GNN (graph layer + GRU), trained with and without the graph.

Runs on a GPU when one is available (Colab or Kaggle), otherwise on every CPU core.
"""
import copy
import os

import numpy as np
import torch
import torch.nn as nn

from common import HORIZON, INPUT_HOURS, TRAIN_END, VALID_START, WEEK, calendar_features, evaluate, load, origins, report, test_origins

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
torch.set_num_threads(os.cpu_count() or 1)  # use every CPU core when there's no GPU
torch.manual_seed(0)
np.random.seed(0)

BATCH_SIZE = 256
LEARNING_RATE = 2e-3
MAX_EPOCHS = 40
PATIENCE = 4               # stop after 4 epochs without improvement
TRAIN_EVERY_HOURS = 2      # forecast start points every 2 hours: half the samples, nearly the same information
FINE_TUNE_EPOCHS = 8       # only used by walk_forward.py --fine-tune


def normalized_adjacency(adjacency: np.ndarray, use_graph: bool) -> torch.Tensor:
    n = len(adjacency)
    if not use_graph:
        return torch.eye(n)  # ablation: every intersection only sees itself
    a = adjacency + np.eye(n, dtype=np.float32)  # self-loops: each node keeps its own signal
    inverse_sqrt_degree = 1.0 / np.sqrt(a.sum(axis=1))
    return torch.tensor(a * inverse_sqrt_degree[:, None] * inverse_sqrt_degree[None, :])  # D^-1/2 (A+I) D^-1/2


class TrafficGNN(nn.Module):
    def __init__(self, n_nodes: int, in_features: int, future_features: int, hidden: int = 32, embedding: int = 8):
        super().__init__()
        self.graph_linear = nn.Linear(in_features, hidden)
        self.gru = nn.GRU(hidden, hidden, batch_first=True)
        self.node_embedding = nn.Embedding(n_nodes, embedding)  # lets each intersection learn its own quirks
        self.head = nn.Sequential(
            nn.Linear(hidden + embedding + HORIZON * future_features + HORIZON, 64),
            nn.ReLU(),
            nn.Linear(64, HORIZON),
        )

    def forward(self, x, future, last_week, adjacency):
        # x [B, 24, N, F] past hours; future [B, 24, Ff] calendar of the forecast hours; last_week [B, N, 24]
        batch, steps, nodes, _ = x.shape
        mixed = torch.einsum("nm,btmf->btnf", adjacency, x)          # each node averages with its road neighbours
        hidden = torch.relu(self.graph_linear(mixed))                # space: graph layer
        hidden = hidden.permute(0, 2, 1, 3).reshape(batch * nodes, steps, -1)
        _, last = self.gru(hidden)                                   # time: GRU over the past 24 hours
        last = last[-1].reshape(batch, nodes, -1)
        node_info = self.node_embedding.weight.expand(batch, nodes, -1)
        future_info = future.reshape(batch, 1, -1).expand(batch, nodes, -1)
        return self.head(torch.cat([last, node_info, future_info, last_week], dim=-1))  # [B, N, 24]


def masked_l1(predicted: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    mask = ~torch.isnan(target)
    if not mask.any():
        return (predicted * 0).sum()
    return (predicted[mask] - target[mask]).abs().mean()


def build(data, origin_list, mean, std, calendar):
    normalized = (data.volumes - mean) / std
    filled = np.nan_to_num(normalized, nan=0.0)  # 0 = this intersection's average after normalising
    n = data.volumes.shape[1]
    x, future, last_week, target = [], [], [], []
    for o in origin_list:
        past = filled[o - INPUT_HOURS:o][..., None]                                   # [24, N, 1]
        past_calendar = np.repeat(calendar[o - INPUT_HOURS:o][:, None, :], n, axis=1) # [24, N, 6]
        x.append(np.concatenate([past, past_calendar], axis=-1))
        future.append(calendar[o:o + HORIZON])
        last_week.append(filled[o - WEEK:o - WEEK + HORIZON].T)
        target.append(normalized[o:o + HORIZON].T)                                    # NaN kept: masked in the loss
    return [torch.tensor(np.stack(a), dtype=torch.float32, device=DEVICE) for a in (x, future, last_week, target)]


def train_and_predict(data, use_graph: bool, train_end=TRAIN_END, valid_start=VALID_START,
                      test_days=None, init_state=None):
    """Returns (predictions in detector counts, the trained weights). Pass init_state to fine-tune."""
    # Normalisation stats come from the first training period and stay fixed, so a fine-tuned
    # model always sees inputs on the same scale. They only use past data: no leakage.
    stats_mask = data.times < min(train_end, TRAIN_END)
    mean = np.nanmean(data.volumes[stats_mask], axis=0)
    std = np.maximum(np.nanstd(data.volumes[stats_mask], axis=0), 1.0)
    calendar = calendar_features(data.times)
    adjacency = normalized_adjacency(data.adjacency, use_graph).to(DEVICE)

    train = build(data, origins(data.times, data.times[0], valid_start, every_hours=TRAIN_EVERY_HOURS), mean, std, calendar)
    valid = build(data, origins(data.times, valid_start, train_end), mean, std, calendar)
    test = build(data, test_days if test_days is not None else test_origins(data), mean, std, calendar)

    model = TrafficGNN(n_nodes=len(mean), in_features=train[0].shape[-1], future_features=train[1].shape[-1]).to(DEVICE)
    max_epochs = MAX_EPOCHS
    if init_state is not None:
        model.load_state_dict(init_state)  # continue from last week's model instead of starting over
        max_epochs = FINE_TUNE_EPOCHS
    optimiser = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE, weight_decay=1e-4)
    best_loss, best_state, bad_epochs = float("inf"), copy.deepcopy(model.state_dict()), 0

    for epoch in range(max_epochs):
        model.train()
        order = torch.randperm(len(train[0]), device=DEVICE)
        for start in range(0, len(order), BATCH_SIZE):
            idx = order[start:start + BATCH_SIZE]
            loss = masked_l1(model(train[0][idx], train[1][idx], train[2][idx], adjacency), train[3][idx])
            optimiser.zero_grad()
            loss.backward()
            optimiser.step()

        model.eval()
        with torch.no_grad():
            valid_loss = masked_l1(model(valid[0], valid[1], valid[2], adjacency), valid[3]).item()
        print(f"  epoch {epoch:2d}  validation L1 {valid_loss:.4f}", flush=True)
        if valid_loss < best_loss - 1e-4:
            best_loss, best_state, bad_epochs = valid_loss, copy.deepcopy(model.state_dict()), 0
        else:
            bad_epochs += 1
            if bad_epochs >= PATIENCE:
                break

    model.load_state_dict(best_state)
    with torch.no_grad():
        predicted = model(test[0], test[1], test[2], adjacency).cpu().numpy()
    return np.clip(predicted * std[None, :, None] + mean[None, :, None], 0, None), best_state


def main() -> None:
    data = load()
    test = test_origins(data)
    print(f"Training on {DEVICE}")
    for use_graph, name in [(True, "GNN (graph + GRU)"), (False, "Same model without graph")]:
        print(f"Training {name}")
        predicted, _ = train_and_predict(data, use_graph)
        report(evaluate(name, predicted, data, test))


if __name__ == "__main__":
    main()
