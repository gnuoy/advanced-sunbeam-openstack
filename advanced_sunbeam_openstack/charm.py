# Copyright 2021 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Base classes for defining a charm using the Operator framework.

This library provided OSBaseOperatorCharm and OSBaseOperatorAPICharm. The
charm classes use advanced_sunbeam_openstack.relation_handlers.RelationHandler
objects to interact with relations. These objects also provide contexts which
can be used when defining templates.

In addition to the Relation handlers the charm class can also use
advanced_sunbeam_openstack.config_contexts.ConfigContext objects which
can be used when rendering templates, these are not specific to a relation.

The charm class interacts with the containers it is managing via
advanced_sunbeam_openstack.container_handlers.PebbleHandler. The
PebbleHandler defines the pebble layers, manages pushing
configuration to the containers and managing the service running
in the container.
"""

import logging
from typing import List

import ops.charm
import ops.framework
import ops.model

import advanced_sunbeam_openstack.config_contexts as sunbeam_config_contexts
import advanced_sunbeam_openstack.container_handlers as sunbeam_chandlers
import advanced_sunbeam_openstack.core as sunbeam_core
import advanced_sunbeam_openstack.relation_handlers as sunbeam_rhandlers


logger = logging.getLogger(__name__)


class OSBaseOperatorCharm(ops.charm.CharmBase):
    """Base charms for OpenStack operators."""

    _state = ops.framework.StoredState()

    def __init__(self, framework):
        super().__init__(framework)
        self._state.set_default(bootstrapped=False)
        self.relation_handlers = self.get_relation_handlers()
        self.pebble_handlers = self.get_pebble_handlers()
        self.framework.observe(self.on.config_changed,
                               self._on_config_changed)

    def can_add_handler(self, relation_name, handlers):
        if relation_name not in self.meta.relations.keys():
            logging.debug(
                f"Cannot add handler for relation {relation_name}, relation "
                "not present in charm metadata")
            return False
        if relation_name in [h.relation_name for h in handlers]:
            logging.debug(
                f"Cannot add handler for relation {relation_name}, handler "
                "already present")
            return False
        return True

    def get_relation_handlers(self, handlers=None) -> List[
            sunbeam_rhandlers.RelationHandler]:
        """Relation handlers for the service."""
        handlers = handlers or []
        if self.can_add_handler('amqp', handlers):
            self.amqp = sunbeam_rhandlers.AMQPHandler(
                self,
                'amqp',
                self.configure_charm,
                self.config.get('rabbitmq-user') or self.service_name,
                self.config.get('rabbitmq-vhost') or 'openstack')
            handlers.append(self.amqp)
        db_svc = f'{self.service_name}-db'
        if self.can_add_handler(db_svc, handlers):
            self.db = sunbeam_rhandlers.DBHandler(
                self,
                db_svc,
                self.configure_charm)
            handlers.append(self.db)
        if self.can_add_handler('shared-db', handlers):
            self.db = sunbeam_rhandlers.SharedDBHandler(
                self,
                'shared-db',
                [self.service_name],
                self.configure_charm)
            handlers.append(self.db)
        if self.can_add_handler('ingress', handlers):
            self.ingress = sunbeam_rhandlers.IngressHandler(
                self,
                'ingress',
                self.service_name,
                self.default_public_ingress_port,
                self.configure_charm)
            handlers.append(self.ingress)
        if self.can_add_handler('peers', handlers):
            self.peers = sunbeam_rhandlers.BasePeerHandler(
                self,
                'peers',
                self.configure_charm)
            handlers.append(self.peers)
        return handlers

    def get_pebble_handlers(self) -> List[sunbeam_chandlers.PebbleHandler]:
        """Pebble handlers for the operator."""
        return [
            sunbeam_chandlers.PebbleHandler(
                self,
                self.service_name,
                self.service_name,
                self.container_configs,
                self.template_dir,
                self.openstack_release,
                self.configure_charm)]

    def configure_charm(self, event) -> None:
        """Catchall handler to cconfigure charm services."""
        if not self.relation_handlers_ready():
            logging.debug("Aborting charm relations not ready")
            return

        for ph in self.pebble_handlers:
            if ph.pebble_ready:
                ph.init_service(self.contexts())

        for ph in self.pebble_handlers:
            if not ph.service_ready:
                logging.debug("Aborting container service not ready")
                return

        if not self.bootstrapped():
            self._do_bootstrap()

        self.unit.status = ops.model.ActiveStatus()
        self._state.bootstrapped = True

    @property
    def container_configs(self) -> List[sunbeam_core.ContainerConfigFile]:
        """Container configuration files for the operator."""
        return []

    @property
    def config_contexts(self) -> List[
            sunbeam_config_contexts.CharmConfigContext]:
        """Configuration adapters for the operator."""
        return [
            sunbeam_config_contexts.CharmConfigContext(self, 'options')]

    @property
    def handler_prefix(self) -> str:
        """Prefix for handlers??"""
        return self.service_name.replace('-', '_')

    @property
    def container_names(self):
        """Containers that form part of this service."""
        return [self.service_name]

    @property
    def template_dir(self) -> str:
        """Directory containing Jinja2 templates."""
        return 'src/templates'

    def _on_config_changed(self, event):
        self.configure_charm(None)

    def containers_ready(self) -> bool:
        """Determine whether all containers are ready for configuration."""
        for ph in self.pebble_handlers:
            if not ph.service_ready:
                logger.info(f"Container incomplete: {ph.container_name}")
                return False
        return True

    def relation_handlers_ready(self) -> bool:
        """Determine whether all relations are ready for use."""
        for handler in self.relation_handlers:
            if not handler.ready:
                logger.info(f"Relation {handler.relation_name} incomplete")
                return False
        return True

    def contexts(self) -> sunbeam_core.OPSCharmContexts:
        """Construct context for rendering templates."""
        ra = sunbeam_core.OPSCharmContexts(self)
        for handler in self.relation_handlers:
            if handler.relation_name not in self.meta.relations.keys():
                logger.info(
                    f"Dropping handler for relation {handler.relation_name}, "
                    "relation not present in charm metadata")
                continue
            if handler.ready:
                ra.add_relation_handler(handler)
        ra.add_config_contexts(self.config_contexts)
        return ra

    def _do_bootstrap(self) -> None:
        """Bootstrap the service ready for operation.

        This method should be overridden as part of a concrete
        charm implementation
        """
        pass

    def bootstrapped(self) -> bool:
        """Determine whether the service has been boostrapped."""
        return self._state.bootstrapped

    def leader_set(self, key: str, value: str) -> None:
        """Set data on the peer relation."""
        self.peers.set_app_data(key, value)

    def leader_get(self, key: str) -> str:
        """Retrieeve data from the peer relation."""
        return self.peers.get_app_data(key)


class OSBaseOperatorAPICharm(OSBaseOperatorCharm):
    """Base class for OpenStack API operators"""

    def __init__(self, framework):
        super().__init__(framework)
        self._state.set_default(db_ready=False)

    @property
    def service_endpoints(self):
        return []

    def get_relation_handlers(self, handlers=None) -> List[
            sunbeam_rhandlers.RelationHandler]:
        """Relation handlers for the service."""
        handlers = handlers or []
        if self.can_add_handler('identity-service', handlers):
            self.id_svc = sunbeam_rhandlers.IdentityServiceRequiresHandler(
                self,
                'identity-service',
                self.configure_charm,
                self.service_endpoints,
                self.model.config['region'])
            handlers.append(self.id_svc)
        handlers = super().get_relation_handlers(handlers)
        return handlers

    @property
    def service_url(self):
        return f'http://{self.service_name}:{self.default_public_ingress_port}'

    @property
    def public_url(self):
        return self.service_url

    @property
    def admin_url(self):
        return self.service_url

    @property
    def internal_url(self):
        return self.service_url

    def get_pebble_handlers(self) -> List[sunbeam_chandlers.PebbleHandler]:
        """Pebble handlers for the service"""
        return [
            sunbeam_chandlers.WSGIPebbleHandler(
                self,
                self.service_name,
                self.service_name,
                self.container_configs,
                self.template_dir,
                self.openstack_release,
                self.configure_charm,
                f'wsgi-{self.service_name}')]

    @property
    def container_configs(self) -> List[sunbeam_core.ContainerConfigFile]:
        """Container configuration files for the service."""
        _cconfigs = super().container_configs
        _cconfigs.extend([
            sunbeam_core.ContainerConfigFile(
                [self.wsgi_container_name],
                self.service_conf,
                self.service_user,
                self.service_group)])
        return _cconfigs

    @property
    def service_user(self) -> str:
        """Service user file and directory ownership."""
        return self.service_name

    @property
    def service_group(self) -> str:
        """Service group file and directory ownership."""
        return self.service_name

    @property
    def service_conf(self) -> str:
        """Service default configuration file."""
        return f'/etc/{self.service_name}/{self.service_name}.conf'

    @property
    def config_contexts(self) -> List[sunbeam_config_contexts.ConfigContext]:
        """Generate list of configuration adapters for the charm."""
        _cadapters = super().config_contexts
        _cadapters.extend([
            sunbeam_config_contexts.WSGIWorkerConfigContext(
                self,
                'wsgi_config')])
        return _cadapters

    @property
    def wsgi_container_name(self) -> str:
        """Name of the WSGI application container."""
        return self.service_name

    @property
    def default_public_ingress_port(self) -> int:
        """Port to use for ingress access to service."""
        raise NotImplementedError
