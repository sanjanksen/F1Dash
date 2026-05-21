"""Self-contained analytical features.

Each module under this package defines one Feature subclass. The startup
module-walk in registry.py imports them all, triggering @register_feature
side effects. The rest of the system (tools.py, chat.py, AnswerRenderer)
reads from FEATURE_REGISTRY rather than hardcoding feature knowledge.
"""
