# -*- coding: utf-8 -*-
"""
Régression logistique binaire en Python pur (descente de gradient batch, L2).

Suffisante pour un premier Agent ML. Remplacement possible par scikit-learn
plus tard sans changer l'interface (fit / predict).
"""

import math


def sigmoid(z):
    # Version numériquement stable.
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


def fit_logreg(X, y, lr=0.5, epochs=30, l2=0.01):
    """Entraîne un classifieur logistique. X : liste de vecteurs, y : 0/1."""
    n = len(X)
    d = len(X[0])
    w = [0.0] * d
    b = 0.0
    for _ in range(epochs):
        gw = [0.0] * d
        gb = 0.0
        for i in range(n):
            xi = X[i]
            z = b + sum(w[j] * xi[j] for j in range(d))
            p = sigmoid(z)
            err = p - y[i]
            for j in range(d):
                gw[j] += err * xi[j]
            gb += err
        for j in range(d):
            w[j] -= lr * (gw[j] / n + l2 * w[j])
        b -= lr * (gb / n)
    return w, b


def predict_proba(w, b, x):
    z = b + sum(w[j] * x[j] for j in range(len(w)))
    return sigmoid(z)


def predict_logreg(w, b, x):
    return 1 if predict_proba(w, b, x) >= 0.5 else 0
