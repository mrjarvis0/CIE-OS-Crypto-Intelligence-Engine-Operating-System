"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.alerts.subscriptions

Purpose:
    Alert subscriptions.
"""

from __future__ import annotations

from typing import Any


class SubscriptionManager:
    """
    Manages subscriptions to alert topics.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[str]] = {}

    def subscribe(self, subscriber: str, topic: str) -> None:
        """
        Subscribe a subscriber to a topic (idempotent).
        """
        subscribers = self._subscribers.setdefault(topic, [])
        if subscriber not in subscribers:
            subscribers.append(subscriber)

    def unsubscribe(self, subscriber: str, topic: str) -> None:
        """
        Remove a subscriber from a topic.
        """
        if topic in self._subscribers:
            self._subscribers[topic] = [
                s for s in self._subscribers[topic] if s != subscriber
            ]
            if not self._subscribers[topic]:
                del self._subscribers[topic]

    def subscribers_for(self, topic: str) -> list[str]:
        """
        Return subscribers for a topic.
        """
        return list(self._subscribers.get(topic, []))
