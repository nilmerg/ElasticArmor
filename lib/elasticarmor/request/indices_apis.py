# ElasticArmor | (c) 2016 NETWAYS GmbH | GPLv2+

from elasticarmor.auth import MultipleIncludesError
from elasticarmor.request import *
from elasticarmor.util.elastic import FilterString


class CreateIndexApiRequest(ElasticRequest):
    locations = {
        'PUT': '/{index}',
        'POST': '/{index}'
    }

    index_settings = {
        'settings': None,
        'creation_date': None,
        'mappings': 'api/indices/create/mappings',
        'warmers': 'api/indices/create/warmers',
        'aliases': 'api/indices/create/aliases'
    }

    @Permission('api/indices/create/index')
    def inspect(self, client):
        if not self.json:
            return

        unknown = next((kw for kw in self.json if kw not in self.index_settings), None)
        if unknown is not None:
            raise PermissionError('Unknown index setting: {0}'.format(unknown))

        missing_permissions = []
        for setting, permission in self.index_settings.iteritems():
            if permission is not None and setting in self.json and not client.can(permission, self.index):
                missing_permissions.append(permission)

        if missing_permissions:
            raise PermissionError('You are missing the following permissions: {0}'
                                  ''.format(', '.join(missing_permissions)))


class DeleteIndexApiRequest(ElasticRequest):
    locations = {
        'DELETE': '/{indices}'
    }

    @Permission('api/indices/delete/index')
    def inspect(self, client):
        pass


class GetIndexApiRequest(ElasticRequest):
    locations = {
        'HEAD': '/{indices}',
        'GET': [
            '/{indices}',
            '/{indices}/{keywords}'
        ]
    }

    index_settings = {
        '_settings': 'api/indices/get/settings',
        '_mappings': 'api/indices/get/mappings',
        '_warmers': 'api/indices/get/warmers',
        '_aliases': 'api/indices/get/aliases'
    }

    def inspect(self, client):
        index_filter = client.create_filter_string('api/indices/get/*', FilterString.from_string(self.indices))
        if index_filter is None:
            raise PermissionError('You are not permitted to access any settings of the given index or indices.')
        elif index_filter:
            self.path = self.path.replace(self.indices, str(index_filter))

        if self.command != 'HEAD':
            keywords = [s.strip() for s in self.get_match('keywords', '').split(',') if s]
            unknown = next((kw for kw in keywords if kw not in self.index_settings), None)
            if unknown is not None:
                raise PermissionError('Unknown index setting: {0}'.format(unknown))

            permitted_settings, missing_permissions = [], {}
            for setting, permission in self.index_settings.iteritems():
                if not keywords or setting in keywords:
                    for index in index_filter.iter_patterns():
                        if client.can(permission, index):
                            permitted_settings.append(setting)
                        elif setting in keywords:
                            missing_permissions.setdefault(permission, []).append(str(index))

            if missing_permissions:
                permission_hint = ', '.join('{0} ({1})'.format(permission, ', '.join(indices))
                                            for permission, indices in missing_permissions.iteritems())
                raise PermissionError('You are missing the following permissions: {0}'.format(permission_hint))
            elif not keywords and len(permitted_settings) < len(self.index_settings):
                self.path = '/'.join((self.path.rstrip('/'), ','.join(permitted_settings)))


class OpenIndexApiRequest(ElasticRequest):
    locations = {
        'POST': '/{indices}/_open'
    }

    @Permission('api/indices/open')
    def inspect(self, client):
        pass


class CloseIndexApiRequest(ElasticRequest):
    locations = {
        'POST': '/{indices}/_close'
    }

    @Permission('api/indices/close')
    def inspect(self, client):
        pass


class CreateMappingApiRequest(ElasticRequest):
    locations = {
        'PUT': [
            '/_mapping{s}/{document}',
            '/{indices}/_mapping{s}/{document}'
        ]
    }

    def inspect(self, client):
        restricted_types = client.is_restricted('types')
        requested_indices = FilterString.from_string(self.get_match('indices', ''))

        try:
            index_filter = client.create_filter_string('api/indices/create/mappings', requested_indices,
                                                       single=restricted_types)
        except MultipleIncludesError as error:
            raise PermissionError(
                'You are restricted to specific types. To create type mappings, please pick a'
                ' single index from the following list: {0}'.format(', '.join(error.includes)))
        else:
            if index_filter is None:
                raise PermissionError('You are not permitted to create mappings in the given indices.')

        if restricted_types:
            requested_index = index_filter.combined[0] if index_filter.combined else index_filter[0]
            if not client.can('api/indices/create/mappings', str(requested_index), self.document):
                raise PermissionError('You are not permitted to create a mapping for this document type.')

        if index_filter:
            self.path = '/{0}/_mappings/{1}'.format(index_filter, self.document)


class GetMappingApiRequest(ElasticRequest):
    before = 'GetIndexApiRequest'

    locations = {
        'GET': [
            '/_mapping{s}',
            '/{indices}/_mapping{s}',
            '/_mapping{s}/{documents}',
            '/{indices}/_mapping{s}/{documents}'
        ],
        'HEAD': '/{indices}/{documents}'
    }

    def inspect(self, client):
        restricted_types = client.is_restricted('types')
        requested_indices = FilterString.from_string(self.get_match('indices', ''))

        try:
            index_filter = client.create_filter_string('api/indices/get/mappings', requested_indices,
                                                       single=restricted_types)
        except MultipleIncludesError as error:
            raise PermissionError(
                'You are restricted to specific types. To retrieve type mappings, please pick a'
                ' single index from the following list: {0}'.format(', '.join(error.includes)))
        else:
            if index_filter is None:
                raise PermissionError('You are not permitted to access the mappings of the given indices.')

        if restricted_types:
            requested_types = FilterString.from_string(self.get_match('documents', ''))
            type_filter = client.create_filter_string('api/indices/get/mappings', requested_types, index_filter)
            if type_filter is None:
                raise PermissionError('You are not permitted to access the mappings of the given types.')
        else:
            type_filter = self.get_match('documents')

        if index_filter:
            if type_filter:
                if self.command == 'HEAD':
                    self.path = '/{0}/{1}'.format(index_filter, type_filter)
                else:
                    self.path = '/{0}/_mappings/{1}'.format(index_filter, type_filter)
            else:
                self.path = '/{0}/_mappings'.format(index_filter)


class GetFieldMappingApiRequest(ElasticRequest):
    locations = {
        'GET': [
            '/{indices}/_mapping/field/{fields}',
            '/{indices}/{documents}/_mapping/field/{fields}',
            '/{indices}/_mapping/{documents}/field/{fields}'
        ]
    }

    def inspect(self, client):
        restricted_types = client.is_restricted('types')
        requested_indices = FilterString.from_string(self.indices)

        try:
            index_filter = client.create_filter_string('api/indices/get/mappings', requested_indices,
                                                       single=restricted_types)
        except MultipleIncludesError as error:
            raise PermissionError(
                'You are restricted to specific types. To retrieve field mappings, please pick a'
                ' single index from the following list: {0}'.format(', '.join(error.includes)))
        else:
            if index_filter is None:
                raise PermissionError('You are not permitted to access the mappings of the given indices.')

        if restricted_types:
            requested_types = FilterString.from_string(self.get_match('documents', ''))
            type_filter = client.create_filter_string('api/indices/get/mappings', requested_types, index_filter)
            if type_filter is None:
                raise PermissionError('You are not permitted to access the mappings of the given types.')
        else:
            type_filter = self.get_match('documents')

        if type_filter:
            self.path = '/{0}/_mapping/{1}/field/{2}'.format(index_filter, type_filter, self.fields)
        else:
            self.path = '/{0}/_mapping/field/{1}'.format(index_filter, self.fields)


class DeleteMappingApiRequest(ElasticRequest):
    before = 'DeleteApiRequest'
    locations = {
        'DELETE': [
            '/{indices}/_mapping{s}',
            '/{indices}/{documents}/_mapping{s}',
            '/{indices}/_mapping{s}/{documents}'
        ]
    }

    @Permission('api/indices/delete/mappings')
    def inspect(self, client):
        pass


class CreateAliasApiRequest(ElasticRequest):
    locations = {
        'POST': '/_aliases',
        'PUT': '/{indices}/_alias{es}/{name}'
    }

    @Permission('api/indices/create/aliases')
    def inspect(self, client):
        pass


class DeleteAliasApiRequest(ElasticRequest):
    locations = {
        'DELETE': '/{indices}/_alias{es}/{names}'
    }

    @Permission('api/indices/delete/aliases')
    def inspect(self, client):
        pass


class GetAliasApiRequest(ElasticRequest):
    before = 'GetIndexApiRequest'
    locations = {
        'GET': [
            '/_alias',
            '/_alias/{name}',
            '/{indices}/_alias',
            '/{indices}/_alias/{name}'
        ],
        'HEAD': [
            '/_alias/{name}',
            '/{indices}/_alias/{name}'
        ]
    }

    def inspect(self, client):
        requested_indices = FilterString.from_string(self.get_match('indices', ''))
        index_filter = client.create_filter_string('api/indices/get/aliases', requested_indices)
        if index_filter is None:
            raise PermissionError('You are not permitted to access aliases of the given indices.')
        elif index_filter:
            self.path = '/{0}/_alias/{1}'.format(index_filter, self.get_match('name', ''))


class UpdateIndexSettingsApiRequest(ElasticRequest):
    locations = {
        'PUT': [
            '/_settings',
            '/{indices}/_settings'
        ]
    }

    @Permission('api/indices/update/settings')
    def inspect(self, client):
        pass


class GetIndexSettingsApiRequest(ElasticRequest):
    before = 'GetIndexApiRequest'
    locations = {
        'GET': [
            '/_settings',
            '/{indices}/_settings'
        ]
    }

    def inspect(self, client):
        requested_indices = FilterString.from_string(self.get_match('indices', ''))
        index_filter = client.create_filter_string('api/indices/get/settings', requested_indices)
        if index_filter is None:
            raise PermissionError(
                'You are not permitted to access the general settings of the given index or indices.')
        elif index_filter:
            self.path = '/{0}/_settings'.format(index_filter)


class AnalyzeApiRequest(ElasticRequest):
    before = 'GetIndexApiRequest'
    locations = {
        'GET': [
            '/_analyze',
            '/{index}/_analyze'
        ],
        'POST': [
            '/_analyze',
            '/{index}/_analyze'
        ]
    }

    @Permission('api/indices/analyze')
    def inspect(self, client):
        pass


class CreateIndexTemplateApiRequest(ElasticRequest):
    locations = {
        'PUT': '/_template/{name}'
    }

    @Permission('api/indices/create/templates')
    def inspect(self, client):
        pass


class DeleteIndexTemplateApiRequest(ElasticRequest):
    locations = {
        'DELETE': '/_template/{name}'
    }

    @Permission('api/indices/delete/templates')
    def inspect(self, client):
        pass


class GetIndexTemplateApiRequest(ElasticRequest):
    locations = {
        'GET': [
            '/_template',
            '/_template/{names}'
        ]
    }

    @Permission('api/indices/get/templates')
    def inspect(self, client):
        pass


class CreateIndexWarmerApiRequest(ElasticRequest):
    locations = {
        'PUT': [
            '/_warmer{s}/{identifier}',
            '/{indices}/_warmer{s}/{identifier}',
            '/{indices}/{documents}/_warmer{s}/{identifier}'
        ]
    }

    @Permission('api/indices/create/warmers', scope='indices')
    def inspect(self, client):
        pass


class DeleteIndexWarmerApiRequest(ElasticRequest):
    locations = {
        'DELETE': '/{indices}/_warmer{s}/{identifiers}'
    }

    @Permission('api/indices/delete/warmers')
    def inspect(self, client):
        pass


class GetIndexWarmerApiRequest(ElasticRequest):
    before = 'GetIndexApiRequest'
    locations = {
        'GET': [
            '/_warmer{s}/{identifiers}',
            '/{indices}/_warmer{s}/{identifiers}'
        ]
    }

    def inspect(self, client):
        requested_indices = FilterString.from_string(self.get_match('indices', ''))
        index_filter = client.create_filter_string('api/indices/get/warmers', requested_indices)
        if index_filter is None:
            raise PermissionError('You are not permitted to access warmers of the given indices.')
        elif index_filter:
            self.path = '/{0}/_warmers/{1}'.format(index_filter, self.identifiers)


class IndexStatsApiRequest(ElasticRequest):
    before = 'GetIndexApiRequest'
    locations = {
        'GET': [
            '/_stats',
            '/{indices}/_stats'
        ]
    }

    @Permission('api/indices/stats')
    def inspect(self, client):
        pass


class IndexSegmentsApiRequest(ElasticRequest):
    before = 'GetIndexApiRequest'
    locations = {
        'GET': [
            '/_segments',
            '/{indices}/_segments'
        ]
    }

    @Permission('api/indices/segments')
    def inspect(self, client):
        pass


class IndexRecoveryApiRequest(ElasticRequest):
    before = 'GetIndexApiRequest'
    locations = {
        'GET': [
            '/_recovery',
            '/{indices}/_recovery'
        ]
    }

    @Permission('api/indices/recovery')
    def inspect(self, client):
        pass


class IndexCacheApiRequest(ElasticRequest):
    locations = {
        'POST': [
            '/_cache/clear',
            '/{indices}/_cache/clear'
        ]
    }

    @Permission('api/indices/cache/clear')
    def inspect(self, client):
        pass


class IndexFlushApiRequest(ElasticRequest):
    locations = {
        'POST': [
            '/_flush',
            '/_flush/synced',
            '/{indices}/_flush',
            '/{indices}/_flush/synced'
        ]
    }

    @Permission('api/indices/flush')
    def inspect(self, client):
        pass


class IndexRefreshApiRequest(ElasticRequest):
    locations = {
        'POST': [
            '/_refresh',
            '/{indices}/_refresh'
        ]
    }

    def inspect(self, client):
        requested_indices = FilterString.from_string(self.get_match('indices', ''))
        index_filter = client.create_filter_string('api/indices/refresh', requested_indices)
        if index_filter is None:
            raise PermissionError('You are not permitted to refresh the given indices.')
        elif index_filter:
            self.path = '/{0}/_refresh'.format(index_filter)


class IndexOptimizeApiRequest(ElasticRequest):
    locations = {
        'POST': [
            '/_optimize',
            '/{indices}/_optimize'
        ]
    }

    @Permission('api/indices/optimize')
    def inspect(self, client):
        pass


class IndexUpgradeApiRequest(ElasticRequest):
    before = 'GetIndexApiRequest'
    locations = {
        'GET': '/{index}/_upgrade',
        'POST': '/{index}/_upgrade'
    }

    @Permission('api/indices/upgrade')
    def inspect(self, client):
        pass
