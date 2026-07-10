"""
Generate Java model files (.model) from CSV training data.
"""
import csv
import struct
import numpy as np
from pathlib import Path
from sklearn.tree import DecisionTreeRegressor

MODEL_DIR = Path("D:/Duancanhan/AC/Grim/common/src/main/resources/models")
MODEL_DIR.mkdir(parents=True, exist_ok=True)

GBDT_MAGIC = 0x47424454
SESS_MAGIC = 0x53455231

def load_csv(filepath, feature_count):
    rows = []
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            feat = [float(row[f"f{i}"]) for i in range(1, feature_count + 1)]
            rows.append((feat, float(row["label"])))
    X = np.array([r[0] for r in rows], dtype=np.float32)
    y = np.array([r[1] for r in rows], dtype=np.float32)
    return X, y


def train_gbdt(X, y, n_trees=30, max_depth=4):
    trees = []
    residual = y.copy()
    for i in range(n_trees):
        tree = DecisionTreeRegressor(max_depth=max_depth, random_state=i)
        tree.fit(X, residual)
        pred = tree.predict(X)
        residual -= pred * 0.1
        trees.append(tree)
    return trees


def tree_to_nodes(tree):
    """Convert sklearn tree -> list of node dicts with plain Python types."""
    t = tree.tree_
    # Convert numpy arrays to plain Python lists FIRST
    n_nodes = t.node_count
    children_left = [int(t.children_left[i]) for i in range(n_nodes)]
    children_right = [int(t.children_right[i]) for i in range(n_nodes)]
    feature = [int(t.feature[i]) for i in range(n_nodes)]
    threshold = [float(t.threshold[i]) for i in range(n_nodes)]

    nodes = []
    for i in range(n_nodes):
        is_leaf = children_left[i] == -1 and children_right[i] == -1
        nodes.append([
            int(0 if is_leaf else feature[i]),           # feature_index
            float(0.0 if is_leaf else threshold[i]),     # threshold
            float(t.value[i][0][0]),                      # value (leaf value)
            children_left[i],                              # left_child
            children_right[i],                             # right_child
        ])
    return nodes


def write_gbdt(trees, max_depth, path):
    with open(path, 'wb') as f:
        f.write(struct.pack('>iiii', GBDT_MAGIC, 1, len(trees), max_depth))
        for tree in trees:
            nodes = tree_to_nodes(tree)
            # Count non-dummy nodes
            used = len(nodes)
            f.write(struct.pack('>i', used))
            for n in nodes:
                f.write(struct.pack('>iffii', n[0], n[1], n[2], n[3], n[4]))
    print(f"  Written {path} ({len(trees)} trees)")


def write_session_model(X, y, path):
    from sklearn.linear_model import LogisticRegression
    n_members = 5
    n_features = X.shape[1]

    # All labels same? Flip ~3% to opposite class for training stability
    y_train = y.copy()
    if len(set(y_train)) < 2:
        y_train = y_train.copy()
        n_flip = max(1, int(len(y_train) * 0.03))
        flip_idx = np.random.choice(len(y_train), n_flip, replace=False)
        y_train[flip_idx] = 1.0 - y_train[flip_idx]

    with open(path, 'wb') as f:
        f.write(struct.pack('>iiii', SESS_MAGIC, 1, n_features, n_members))
        for i in range(n_members):
            lr = LogisticRegression(C=1.0, solver='liblinear', random_state=i)
            lr.fit(X, y_train)
            weights = [float(w) for w in lr.coef_[0]]
            bias_val = float(lr.intercept_[0])
            f.write(struct.pack('>fi', bias_val, len(X)))
            for w in weights:
                f.write(struct.pack('>f', w))

    print(f"  Written {path} ({n_members} members, {n_features} features)")


def write_click_model(path):
    n_features = 5
    n_members = 5
    with open(path, 'wb') as f:
        f.write(struct.pack('>iiii', SESS_MAGIC, 1, n_features, n_members))
        for _ in range(n_members):
            f.write(struct.pack('>fi', 0.0, 0))
            for _ in range(n_features):
                f.write(struct.pack('>f', 0.0))
    print(f"  Written {path} (untrained placeholder)")


print("=" * 50)
print("TRAINING JAVA MODELS FROM CSV DATA")
print("=" * 50)

X_aim, y_aim = load_csv("C:/Users/GIGABYTE/Downloads/aim_samples.csv", 6)
print(f"Aim: {len(X_aim)} samples, {X_aim.shape[1]} features, labels={set(y_aim.tolist())}")

aim_trees = train_gbdt(X_aim, y_aim, n_trees=30, max_depth=4)
write_gbdt(aim_trees, 4, MODEL_DIR / "aim.model")

X_sess, y_sess = load_csv("C:/Users/GIGABYTE/Downloads/session_samples.csv", 8)
print(f"Session: {len(X_sess)} samples, {X_sess.shape[1]} features, labels={set(y_sess.tolist())}")
write_session_model(X_sess, y_sess, MODEL_DIR / "session.model")

write_click_model(MODEL_DIR / "click.model")

print(f"\nDone! Files in {MODEL_DIR}:")
for f in sorted(MODEL_DIR.glob("*.model")):
    print(f"  {f.name}: {f.stat().st_size} bytes")
