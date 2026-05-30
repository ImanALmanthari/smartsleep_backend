# ─────────────────────────────────────────────────────────────────────────────
# predictor.py  –  Personal ML model for sleep score prediction (Steps 9 & 14).
#
# Each user gets their OWN personal model that learns from their feedback.
# This is called "online learning" or "incremental learning" — the model
# is updated one sample at a time, not retrained from scratch.
#
# We use scikit-learn's SGD (Stochastic Gradient Descent) models:
#   - SGDRegressor:  predicts a numeric score (0-100)
#   - SGDClassifier: predicts a category ("Excellent", "Good", "Fair", "Poor")
#
# Models are saved to disk as .joblib files in the /models directory,
# one pair per user: {user_id}_reg.joblib and {user_id}_clf.joblib
# ─────────────────────────────────────────────────────────────────────────────

import joblib   # Library for saving/loading Python objects (ML models) to disk
import os
from typing import Optional, Tuple, List
import numpy as np
from sklearn.linear_model import SGDRegressor, SGDClassifier

# Directory where per-user model files are stored
MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "models")

# The four possible sleep quality classes the classifier can predict
CLASSES = np.array(["Poor", "Fair", "Good", "Excellent"])


class MLPredictor:
    """Personal ML model manager — one model per user.

    Each user has two saved model files:
    - {user_id}_reg.joblib:  SGDRegressor  → predicts numeric sleep score (0-100)
    - {user_id}_clf.joblib:  SGDClassifier → predicts quality class (Poor/Fair/Good/Excellent)

    The cold-start problem: when a user is new (< 14 labelled samples), the
    ML model doesn't exist yet. In that case, predict() returns (None, None)
    and the caller falls back to the rule-based score.
    """

    def __init__(self):
        """Initialise the predictor and ensure the models directory exists."""
        os.makedirs(MODEL_DIR, exist_ok=True)  # Create /models directory if it doesn't exist

    def _paths(self, user_id: str) -> Tuple[str, str]:
        """Get the file paths for this user's regressor and classifier model files.

        Args:
            user_id: The user's UUID string.

        Returns:
            Tuple of (regressor_path, classifier_path).
        """
        return (
            os.path.join(MODEL_DIR, f"{user_id}_reg.joblib"),
            os.path.join(MODEL_DIR, f"{user_id}_clf.joblib"),
        )

    def _load(self, user_id: str) -> Tuple:
        """Load both model files from disk for the given user.

        If a model file doesn't exist yet (user hasn't provided enough feedback),
        that model is returned as None.

        Args:
            user_id: The user's UUID string.

        Returns:
            Tuple of (regressor, classifier). Either or both can be None.
        """
        reg_path, clf_path = self._paths(user_id)
        # Load model from disk if the file exists; otherwise return None
        regressor  = joblib.load(reg_path)  if os.path.exists(reg_path)  else None
        classifier = joblib.load(clf_path) if os.path.exists(clf_path) else None
        return regressor, classifier

    def predict(self, user_id: str, fv: List[float]) -> Tuple[Optional[float], Optional[str]]:
        """Predict the sleep score and quality class using the user's personal model (Step 9).

        This is the "inference" step — we use the model to make a prediction
        without updating it. The model was trained from the user's previous
        feedback sessions.

        Args:
            user_id: The user's UUID string.
            fv:      The 10-element feature vector for tonight's sleep.

        Returns:
            Tuple of (ml_score, user_class):
            - ml_score (float 0-100) or None if no model exists yet
            - user_class ("Poor"/"Fair"/"Good"/"Excellent") or None if no model exists yet
        """
        regressor, classifier = self._load(user_id)
        if not regressor and not classifier:
            return None, None  # Cold start — no personal model yet

        # Reshape to (1, 10): sklearn expects a 2D array even for single predictions
        X = np.array(fv).reshape(1, -1)

        # Make predictions (each .predict() returns an array; we take the first element)
        ml_score   = float(regressor.predict(X)[0])  if regressor  else None
        user_class = str(classifier.predict(X)[0])   if classifier else None
        return ml_score, user_class

    def partial_fit(self, user_id: str, fv: List[float], user_score: float, user_class: str):
        """Update the user's personal model with one new labelled sample (Step 14).

        This is "online learning" — instead of retraining from scratch, we do
        a single gradient descent step to incorporate the new training example.
        partial_fit() is the scikit-learn method for incremental training.

        Called after the user rates their sleep (provides feedback).

        Args:
            user_id:    The user's UUID string.
            fv:         The 10-element feature vector for the night being rated.
            user_score: The user's self-reported sleep quality (0-100).
            user_class: The user's quality label ("Poor"/"Fair"/"Good"/"Excellent").
        """
        regressor, classifier = self._load(user_id)
        reg_path, clf_path = self._paths(user_id)

        # Reshape inputs to the format sklearn expects
        X     = np.array(fv).reshape(1, -1)   # Feature matrix: shape (1, 10)
        y_reg = np.array([user_score])          # Regression target: shape (1,)
        y_clf = np.array([user_class])          # Classification target: shape (1,)

        # If this is the first training call, create fresh models
        if regressor is None:
            regressor = SGDRegressor(max_iter=1000, tol=1e-3, warm_start=True)
        if classifier is None:
            classifier = SGDClassifier(loss="modified_huber", max_iter=1000, tol=1e-3)

        # One incremental training step (gradient descent update)
        regressor.partial_fit(X, y_reg)
        # `classes=CLASSES` must be passed on every call so the classifier
        # knows all possible output labels even if some haven't appeared yet
        classifier.partial_fit(X, y_clf, classes=CLASSES)

        # Persist updated models to disk for future predictions
        joblib.dump(regressor, reg_path)
        joblib.dump(classifier, clf_path)


# Module-level singleton — the entire app shares one MLPredictor instance.
# This avoids repeatedly loading models for every request.
predictor = MLPredictor()
