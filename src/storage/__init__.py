"""Conversation and pet-profile storage kept in the user's browser (design doc phase 2).

The server never keeps conversation text. Values coming back from the browser are
user-editable, so every load goes through validation in src.storage.models.
"""
