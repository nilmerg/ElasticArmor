# ElasticArmor | (c) 2016 NETWAYS GmbH | GPLv2+

import socket

import requests
from ldap import LDAPError

from elasticarmor import *
from elasticarmor.util import format_ldap_error, format_elasticsearch_error
from elasticarmor.util.elastic import SourceFilter, FilterString, FieldsFilter
from elasticarmor.util.mixins import LoggingAware

__all__ = ['AuthorizationError', 'Auth', 'MultipleIncludesError', 'Client']


class AuthorizationError(Exception):
    """Base class for all authorization related exceptions."""
    pass


class Auth(LoggingAware, object):
    """Auth manager class for everything involved in authentication and authorization."""

    def __init__(self, settings):
        self.allow_from = settings.allow_from
        self.role_backend = settings.role_backend
        self.auth_backends = settings.auth_backends
        self.group_backends = settings.group_backends
        self.trusted_proxies = settings.trusted_proxies

    def authenticate(self, client, populate=True):
        """Authenticate the given client and return whether it succeeded or not."""
        if client.username is None or client.password is None:
            # In case we have no authentication credentials check if access by ip[:port] is permitted
            allowed_ports = self.allow_from.get(client.address, [])
            if allowed_ports is not None and (client.port is None or client.port not in allowed_ports):
                return False
            else:
                default_timeout = socket.getdefaulttimeout()
                socket.setdefaulttimeout(2)

                try:
                    hostname = socket.gethostbyaddr(client.address)[0]
                except IOError:
                    hostname = client.address
                finally:
                    socket.setdefaulttimeout(default_timeout)

                client.name = hostname if allowed_ports is None else '%s:%u' % (hostname, client.port)
                client.authenticated = True
        else:
            client.name = client.username
            if self.auth_backends:
                for backend in self.auth_backends:
                    try:
                        if backend.authenticate(client):
                            client.authenticated = True
                            client.default_role = backend.default_role
                            break
                    except LDAPError as error:
                        self.log.error('Failed to authenticate client "%s" using backend "%s". %s.',
                                       client, backend.name, format_ldap_error(error))
                    except requests.RequestException as error:
                        self.log.error('Failed to authenticate client "%s" using backend "%s". Error: %s.',
                                       client, backend.name, format_elasticsearch_error(error))
            else:
                trusted_ports = self.trusted_proxies.get(client.peer_address, [])
                client.authenticated = trusted_ports is None or client.peer_port in trusted_ports

        if client.authenticated and populate:
            self.populate(client)

        return client.authenticated

    def populate(self, client):
        """Populate the group and role memberships of the given client."""
        if self.group_backends and client.username is not None:
            self.log.debug('Fetching group memberships for client "%s"...', client)

            groups, error = [], None
            for backend in self.group_backends:
                try:
                    groups.extend(backend.get_group_memberships(client))
                except LDAPError as error:
                    self.log.error('Failed to fetch ldap group memberships for client "%s" using backend "%s". %s.',
                                   client, backend.name, format_ldap_error(error))

            if groups or error is None:
                client.groups = groups
                self.log.debug('Client "%s" is a member of the following groups: %s',
                               client, ', '.join(client.groups) or 'None')
        else:
            client.groups = []

        if client.groups is not None:
            self.log.debug('Fetching role memberships for client "%s"...', client)

            try:
                client.roles = self.role_backend.get_role_memberships(client)
            except requests.RequestException as error:
                self.log.error('Failed to fetch Elasticsearch role memberships for client "%s". Error: %s',
                               client, format_elasticsearch_error(error))
            else:
                self.log.debug('Client "%s" is a member of the following roles: %s',
                               client, ', '.join(r.id for r in client.roles) or 'None')

    # TODO: Provide a more sophisticated solution, this can't be the only one..
    def _apply_system_defaults(self, client):
        permitted_config_types = []
        if client.can('config/authentication'):
            permitted_config_types.append(CONFIGURATION_TYPE_USER)
        if client.can('config/authorization'):
            permitted_config_types.append(CONFIGURATION_TYPE_ROLE)
            permitted_config_types.append(CONFIGURATION_TYPE_ROLE_USER)
            permitted_config_types.append(CONFIGURATION_TYPE_ROLE_GROUP)

        if permitted_config_types:
            from elasticarmor.auth.role import Role
            if client.is_restricted('indices'):
                client.roles.append(Role('sysconfig', {
                    'indices': [{
                        'permissions': '*',
                        'include': CONFIGURATION_INDEX,
                        'types': [{'include': permitted_config_types}]
                    }]
                }))
            else:
                client.roles.append(Role('sysconfig', {
                    'indices': [
                        {
                            'include': '*',
                            'exclude': CONFIGURATION_INDEX
                        },
                        {
                            'permissions': '*',
                            'include': CONFIGURATION_INDEX,
                            'types': [{'include': permitted_config_types}]
                        }
                    ]
                }))
        elif not client.is_restricted('indices'):
            from elasticarmor.auth.role import Role
            client.roles.append(Role('sysconfig', {
                'indices': [{
                    'include': '*',
                    'exclude': CONFIGURATION_INDEX
                }]
            }))
        else:
            from elasticarmor.auth.role import Pattern
            pattern = Pattern(CONFIGURATION_INDEX)
            for restriction in (r for role in client.roles for r in role.get_restrictions()):
                if restriction.matches(pattern):
                    restriction.excludes.append(pattern)

        # TODO: Once this method is not "the" solution anymore, make
        # sure that this is not required in the new solution as well
        del client._restricted_scope


class MultipleIncludesError(AuthorizationError):
    """Raised by Client.create_filter_string() if more includes than expected were found.

    The includes that were found are available as instance attribute.
    """

    def __init__(self, includes):
        super(MultipleIncludesError, self).__init__('Multiple includes found')
        self.includes = [str(include) for include in includes]


class Client(LoggingAware, object):
    """An object representing a client who is sending a request."""

    def __init__(self, address, port=None):
        self.address = address
        self.port = port

        self.peer_address = None
        self.peer_port = None

        self.name = None
        self.authenticated = False
        self.default_role = None
        self.username = None
        self.password = None
        self.groups = None
        self.roles = None

    def __str__(self):
        """Return a human readable string representation for this client.
        That's either the name, username or the address and port concatenated with a colon.

        """
        if self.name is not None:
            return self.name

        if self.username is not None:
            return self.username

        if self.port is None:
            return self.address

        return '%s:%u' % (self.address, self.port)

    @property
    def restricted_scope(self):
        """The smallest scope within this client is restricted.
        That's either None, 'indices', 'types' or 'fields'.

        """
        try:
            return self._restricted_scope
        except AttributeError:
            scope = None
            for restricted_scope in (role.get_restricted_scope() for role in self.roles):
                if restricted_scope == 'fields':
                    scope = 'fields'
                    break
                elif restricted_scope == 'types':
                    scope = 'types'
                elif scope is None and restricted_scope == 'indices':
                    scope = 'indices'

            self._restricted_scope = scope
            return self._restricted_scope

    def is_restricted(self, scope='indices'):
        """Return whether this client is restricted within the given scope.
        Valid scopes are 'indices', 'types' and 'fields'.

        """
        if self.restricted_scope == scope:
            return True
        elif scope == 'fields':
            return False

        if scope == 'indices':
            return self.restricted_scope is not None
        elif scope == 'types':
            return self.restricted_scope is not None and self.restricted_scope != 'indices'

        raise AssertionError('Invalid scope "{0}" given'.format(scope))

    def can(self, permission, index=None, document_type=None, field=None):
        """Return whether this client has the given permission in the given context."""
        try:
            # If it's a FilterString, use its base pattern instead. Avoids some
            # checks otherwise required to be done in advance by the caller
            if index is not None:
                index = index.base_pattern
                if document_type is not None:
                    document_type = document_type.base_pattern
        except AttributeError:
            pass

        return any(role.permits(permission, index, document_type, field) for role in self.roles)

    def has_restriction(self, index, document_type=None, without_permission=None):
        """Return whether this client is restricted within the given context.
        The optional permission allows to check only for restrictions that do
        not grant the permission in the given context.

        """
        if self.is_restricted('types' if document_type is None else 'fields'):
            try:
                index = index.base_pattern
                if document_type is not None:
                    document_type = document_type.base_pattern
            except AttributeError:
                pass

            for role in self.roles:
                if any(role.get_restrictions(index, document_type, without_permission,
                                             invert=without_permission is not None)):
                    return True

        return False

    # TODO: Make sure no request handler uses single=client.is_restricted(<scope>).
    #       Should be single=client.has_restriction(<scope>) instead!!1
    def create_filter_string(self, permission, filter_string=None, index=None, single=False):
        """Create and return a filter string based on what this client is permitted or is requesting to access.
        May return a empty filter if the client is not restricted at all and None if the client can't access
        anything. Raises MultipleIncludesError if single is True and multiple includes were found.

        """
        if not self.is_restricted('indices' if index is None else 'types'):
            return filter_string or FilterString()  # Bail out early if the client is not restricted at all

        try:
            if index is not None:
                index = index.base_pattern
        except AttributeError:
            pass

        filters = self._collect_filters(permission, filter_string, index)
        if filters is None:
            return  # None of the client's roles permit access to any index or any document type
        elif not filters:
            return filter_string or FilterString()  # Not a single restriction, congratulations!

        prepared_filter_string = FilterString()
        for include, excludes in filters.iteritems():
            prepared_filter_string.append_include(include)
            for exclude in excludes:
                prepared_filter_string.append_exclude(exclude)

        if filter_string:
            # In case the client provides a filter it may be required to adjust
            # it a little. We'd like to be smart after all, don't we? ;)
            if not filter_string.combine(prepared_filter_string):
                return  # Nothing what the client requested remained

            if single and len(filter_string.combined) > 1:
                # Although the client already provides a filter it does still consist of multiple restrictions
                raise MultipleIncludesError(filter_string.combined)
        elif single and len(filters) > 1:
            # We can obviously only provide multiple filters and since it would be unsafe
            # to make an assumption on what filter to return, we'll refuse to return one
            raise MultipleIncludesError(filters.keys())
        else:
            # The client does not provide a source filter so we can simply return our own
            filter_string = prepared_filter_string

        return filter_string

    def create_source_filter(self, permission, index, document_type, source_filter=None):
        """Create and return a source filter based on what this client is permitted or is requesting to access. May
        return a empty filter if the client is not restricted at all and None if the client can't access anything.

        """
        if not self.is_restricted('fields'):
            return source_filter or SourceFilter()  # Bail out early if the client is not restricted at all

        try:
            index = index.base_pattern
            document_type = document_type.base_pattern
        except AttributeError:
            pass

        filters = self._collect_filters(permission, None, index, document_type)
        if filters is None:
            return  # None of the client's roles permit access to the given index or document type
        elif not filters:
            return source_filter or SourceFilter()  # Not a single restriction, congratulations!

        prepared_source_filter = SourceFilter()
        for include, excludes in filters.iteritems():
            prepared_source_filter.includes.append(include)
            prepared_source_filter.excludes.extend(excludes)

        if not source_filter:
            # The client does not provide a source filter so we can simply return our own
            return prepared_source_filter
        elif source_filter.disabled or source_filter.excludes == ['*']:
            # The client does not want any source fields so we shouldn't provide them either
            return source_filter

        # The client does indeed provide a source filter so let's try to be smart here as well :P
        if not source_filter.combine(prepared_source_filter):
            return  # Nothing what the client requested remained

        return source_filter

    def create_fields_filter(self, permission, index, document_type, fields_filter=None):
        """Create and return a fields filter based on what this client is permitted or is requesting to access. May
        return a empty filter if the client is not restricted at all and None if the client can't access anything.

        """
        if not self.is_restricted('fields'):
            return fields_filter or FieldsFilter()  # Bail out early if the client is not restricted at all
        elif fields_filter is not None and not fields_filter:
            return fields_filter  # The client does not want any fields so we shouldn't provide them either

        try:
            index = index.base_pattern
            document_type = document_type.base_pattern
        except AttributeError:
            pass

        filters = self._collect_filters(permission, None, index, document_type)
        if filters is None:
            return  # None of the client's roles permit access to the given index or document type
        elif not filters:
            return fields_filter or FieldsFilter()  # Not a single restriction, congratulations!

        # A fields filter has no idea of excludes, so we can only use includes which do not have any
        # or where all excludes are unnecessary as the client does restrict itself already far enough
        fields = [include for include in filters
                  if not filters[include] or not any(p >= e for p in fields_filter for e in filters[include])]
        if not fields:
            # But if all available filters have required excludes, we can't provide the client with a fields filter
            if fields_filter.requires_source and (len(fields_filter) == 0 or fields_filter[0] == '*'):
                # Except if "_source" is given and the client doesn't specify which stored fields are desired, in which
                # case we're at least able to provide source fields and to pretend that no stored fields are available
                return FieldsFilter(source=True)
        elif fields_filter.combine(FieldsFilter(fields)):
            return fields_filter

    def _collect_filters(self, permission, filter_string=None, index=None, document_type=None):
        """Collect and return the filters for the given context which grant the given permission.
        In case of overlapping filters, only those that give the client the broadest access are
        returned. Returns None if not a single role grants access in the given context.

        """
        from elasticarmor.auth.role import RestrictionsFound  # Placed here to avoid a circular import

        filters, involved_roles, indisposed_roles = {}, {}, 0
        for role in self.roles:
            try:
                restrictions = list(role.get_restrictions(index, document_type, permission))
            except RestrictionsFound:
                # Roles may be able to provide restrictions for the given context but
                # cannot because the required permission is granted by none of them
                indisposed_roles += 1
            else:
                if not restrictions:
                    if not role.permits(permission, index, document_type):
                        # The same applies to roles which are neither able to provide
                        # restrictions nor grant the permission at a higher level
                        indisposed_roles += 1
                    else:
                        # But if a role grants the permission at a higher level, guess what,
                        # the client is obviously not restricted at all in the given context
                        return {}
                else:
                    for restriction in restrictions:
                        for include in restriction.includes:
                            involved_roles[include] = role
                            filters.setdefault(include, []).extend(restriction.excludes)

        if not filters and indisposed_roles == len(self.roles):
            # Not a single role provided restrictions nor felt being responsible
            # for the given context, so the client is not permitted, not at all
            return

        # Remove the most restrictive filters. This is the part that ensures
        # that we're granting the client the broadest access possible
        scope = 'indices' if index is None else 'types' if document_type is None else 'fields'
        for include in filters.keys():
            superior = reduce(lambda a, b: b if b > a else a, filters.iterkeys(), include)
            if include is not superior:
                if filter_string and all(include >= p for p in filter_string.iter_patterns()):
                    # The client may restrict itself already far enough so that the include,
                    # whilst not being the least restrictive one, is still more restrictive.
                    # If that's the case, we must not remove the include but the one which
                    # is superior as otherwise the client may not have the granted access
                    del filters[superior]
                else:
                    # If the include is about to be removed check whether it is possible
                    # to neutralize some of the excludes linked to the less restrictive
                    # filter and if so, exchange them with the include's excludes
                    if involved_roles[include].get_restricted_scope() != scope:
                        # But this is only possible if the include restricts the client not
                        # in another scope than we're collecting filters for. Otherwise the
                        # client may have more access than intended
                        pass
                    elif filters[superior]:
                        excludes = [e for e in filters[superior] if not e >= include]
                        if excludes != filters[superior]:
                            excludes.extend(filters[include])
                            filters[superior] = excludes

                    del filters[include]

        return filters
