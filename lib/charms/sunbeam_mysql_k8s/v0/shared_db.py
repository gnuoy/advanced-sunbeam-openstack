"""
"""

# !/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import uuid
import logging
from ops.relation import ConsumerBase

from ops.framework import (
    StoredState,
    EventBase,
    ObjectEvents,
    EventSource,
    Object,
)
LIBID = "abcdef1234"  # Will change when uploding the charm to charmhub
LIBAPI = 1
LIBPATCH = 0
logger = logging.getLogger(__name__)

class DatabaseConnectedEvent(EventBase):
    """Database connected Event."""

    pass


class DatabaseReadyEvent(EventBase):
    """Database ready for use Event."""

    pass


class DatabaseGoneAwayEvent(EventBase):
    """Database relation has gone-away Event"""

    pass


class DatabaseServerEvents(ObjectEvents):
    """Events class for `on`"""

    connected = EventSource(DatabaseConnectedEvent)
    ready = EventSource(DatabaseReadyEvent)
    goneaway = EventSource(DatabaseGoneAwayEvent)


class SharedDBRequires(Object):
    """
    DatabaseRequires class
    """

    on = DatabaseServerEvents()
    _stored = StoredState()

    def __init__(self, charm, relation_name: str, databases: list):
        super().__init__(charm, relation_name)
        self.charm = charm
        self.relation_name = relation_name
        self.databases = databases
        self.framework.observe(
            self.charm.on[relation_name].relation_joined,
            self._on_database_relation_joined,
        )
        self.framework.observe(
            self.charm.on[relation_name].relation_changed,
            self._on_database_relation_changed,
        )
        self.framework.observe(
            self.charm.on[relation_name].relation_departed,
            self._on_database_relation_changed,
        )
        self.framework.observe(
            self.charm.on[relation_name].relation_broken,
            self._on_database_relation_broken,
        )

    @property
    def _db_rel(self):
        """The AMQP relation."""
        return self.framework.model.get_relation(self.relation_name)

    def _on_database_relation_joined(self, event):
        """Database relation joined."""
        logging.debug("DatabaseRequires on_joined")

    def _on_database_relation_joined(self, event):
        """AMQP relation joined."""
        logging.debug("DatabaseRequires on_joined")
        self.on.connected.emit()
        self.request_access(self.username, self.databases)

    def _on_database_relation_changed(self, event):
        """AMQP relation changed."""
        logging.debug("DatabaseRequires on_changed")
        if self.password:
            self.on.ready.emit()

    def _on_database_relation_broken(self, event):
        """AMQP relation broken."""
        logging.debug("DatabaseRequires on_broken")
        self.on.goneaway.emit()

    def request_access(self, databases: list) -> None:
        """Request access to the AMQP server."""
        if self.model.unit.is_leader():
            logging.debug("Requesting AMQP user and vhost")
            self._db_rel.data[self.charm.app]["databases"] = json.dumps(databases)
