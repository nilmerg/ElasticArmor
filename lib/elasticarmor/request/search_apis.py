# ElasticArmor | (c) 2016 NETWAYS GmbH | GPLv2+

from contextlib import closing
from StringIO import StringIO

from elasticarmor import APP_NAME
from elasticarmor.auth import MultipleIncludesError
from elasticarmor.request import *
from elasticarmor.util.elastic import (SourceFilter, FilterString, QueryDslParser, AggregationParser,
                                       HighlightParser, FieldsFilter)


class SearchApiRequest(ElasticRequest):
    before = [
        'GetIndexApiRequest',
        'IndexApiRequest',
        'GetApiRequest'
    ]

    locations = {
        'GET': [
            '/_search',
            '/{indices}/_search',
            '/{indices}/{documents}/_search'
        ],
        'POST': [
            '/_search',
            '/{indices}/_search',
            '/{indices}/{documents}/_search'
        ]
    }

    _permission_errors = {
        'api/search/explain': {
            'cluster': 'You are not permitted to access scoring explanations.',
            'indices': 'You are not permitted to access scoring explanations of the following indices: {0}',
            'types': 'You are not permitted to access scoring explanations of the following types: {0}',
            'fields': 'You are not permitted to access scoring explanations of the following fields: {0}'
        },
        'api/feature/innerHits': {
            'cluster': 'You are not permitted to access inner hits.',
            'indices': 'You are not permitted to access inner hits of the following indices: {0}',
            'types': 'You are not permitted to access inner hits of the following types: {0}'
        },
        'api/search/suggest': {
            'cluster': 'You are not permitted to perform suggest requests.',
            'indices': 'You are not permitted to perform suggest requests on the following indices: {0}',
            'types': 'You are not permitted to perform suggest requests on the following types: {0}'
        },
        'api/indices/stats': {
            'cluster': 'You are not permitted to access index statistics.',
            'indices': 'You are not permitted to access statistics of the following indices: {0}'
        },
        'api/feature/script': {
            'cluster': 'You are not permitted to utilize scripts.',
            'indices': 'You are not permitted to utilize scripts in the following indices: {0}',
            'types': 'You are not permitted to utilize scripts in the following types: {0}',
            'fields': 'You are not permitted to utilize scripts with the following fields: {0}'
        },
        'api/search/template': {
            'cluster': 'You are not permitted to utilize search templates.',
            'indices': 'You are not permitted to utilize search templates for the following indices: {0}',
            'types': 'You are not permitted to utilize search templates for the following types: {0}'
        },
        'api/feature/moreLikeThis': {
            'cluster': 'You are not permitted to utilize the more_like_this query.',
            'indices': 'You are not permitted to utilize the more_like_this query in the following indices: {0}',
            'types': 'You are not permitted to utilize the more_like_this query in the following types: {0}',
            'fields': 'You are not permitted to utilize the more_like_this query with the following fields: {0}'
        },
        'api/feature/fuzzyLikeThis': {
            'cluster': 'You are not permitted to utilize the fuzzy_like_this or fuzzy_like_this_field query.',
            'indices': 'You are not permitted to utilize the fuzzy_like_this or fuzzy_like_this_field query'
                       ' in the following indices: {0}',
            'types': 'You are not permitted to utilize the fuzzy_like_this or fuzzy_like_this_field query'
                     ' in the following types: {0}',
            'fields': 'You are not permitted to utilize the fuzzy_like_this or fully_like_this_field query'
                      ' with the following fields: {0}'
        }
    }

    def inspect(self, client):
        index_filter, type_filter, source_filter, json = self.inspect_request(
            client, FilterString.from_string(self.get_match('indices', '')),
            FilterString.from_string(self.get_match('documents', '')),
            SourceFilter.from_query(self.query), self.json)

        if self.query.last('q', '').strip() and self.query.last('q').strip() != '*':
            if client.has_restriction(index_filter, type_filter):
                # TODO: Provide a more sophisticated solution once we've got a parser for query strings!
                raise PermissionError(
                    'You are restricted to specific fields and as such cannot utilize the query string search.')

        if not self.query.is_false('explain'):
            self._check_permission('api/search/explain', client, index_filter, type_filter)

        fields_filter = client.create_fields_filter('api/search/documents', index_filter, type_filter,
                                                    FieldsFilter.from_query(self.query))
        if fields_filter is None:
            raise PermissionError('You are not permitted to access any of the requested stored fields.')
        elif fields_filter:
            self.query.update(fields_filter.as_query())

        if index_filter:
            if type_filter:
                self.path = '/{0}/{1}/_search'.format(index_filter, type_filter)
            else:
                self.path = '/{0}/_search'.format(index_filter)

        self.query.discard('_source', '_source_include', '_source_exclude')
        if source_filter:
            self.query.update(source_filter.as_query())

        if json is not None:
            self.body = self.json_encode(json)

    def inspect_request(self, client, requested_indices, requested_types, requested_source=None, json=None):
        # TODO: Error handling for unexpected types
        try:
            index_filter = client.create_filter_string('api/search/documents', requested_indices,
                                                       single=client.is_restricted('types'))
        except MultipleIncludesError as error:
            raise PermissionError(
                'You are restricted to specific types or fields. To use the search api, please pick'
                ' a single index from the following list: {0}'.format(', '.join(error.includes)))
        else:
            if index_filter is None:
                raise PermissionError('You are not permitted to search for documents using'
                                      ' the index filter "{0}".'.format(requested_indices))

        try:
            type_filter = client.create_filter_string('api/search/documents', requested_types,
                                                      index_filter, client.is_restricted('fields'))
        except MultipleIncludesError as error:
            raise PermissionError(
                'You are restricted to specific fields. To use the search api, please pick a'
                ' single type from the following list: {0}'.format(', '.join(error.includes)))
        else:
            if type_filter is None:
                raise PermissionError('You are not permitted to search for documents using'
                                      ' the type filter "{0}".'.format(requested_types))

        if json is not None:
            if json.get('stats'):
                self._check_permission('api/indices/stats', client, index_filter)
            if json.get('facets'):
                self._check_permission('api/feature/facets', client, index_filter, type_filter)
            if json.get('script_fields'):
                self._check_permission('api/feature/script', client, index_filter, type_filter)
            if json.get('explain', False):
                self._check_permission('api/search/explain', client, index_filter, type_filter)
            if json.get('inner_hits'):
                self._check_permission('api/feature/innerHits', client, index_filter, type_filter)
            if json.get('suggest'):
                self._check_permission('api/search/suggest', client, index_filter, type_filter)

        json_updated = False
        if type_filter and client.is_restricted('fields'):
            if json is not None and 'fielddata_fields' in json:
                fielddata_filter = client.create_fields_filter('api/search/documents', index_filter, type_filter,
                                                               FieldsFilter.from_json(json['fielddata_fields']))
                if fielddata_filter is None:
                    raise PermissionError('You are not permitted to access any of the requested fielddata fields.')
                elif fielddata_filter:
                    json['fielddata_fields'] = fielddata_filter.as_json()
                    json_updated = True

            inspect_source = True
            if json is not None and ('fields' in json or 'partial_fields' in json):
                inspect_source = '_source' in json
                if 'fields' in json:
                    fields_filter = client.create_fields_filter('api/search/documents', index_filter, type_filter,
                                                                FieldsFilter.from_json(json['fields']))
                    if fields_filter is None:
                        raise PermissionError('You are not permitted to access any of the requested stored fields.')
                    elif fields_filter:
                        json['fields'] = fields_filter.as_json()
                        json_updated = True
                        if fields_filter.requires_source:
                            inspect_source = True

                if 'partial_fields' in json:
                    partial_fields = {}
                    for partial, partial_body in json['partial_fields'].iteritems():
                        permitted = client.create_source_filter('api/search/documents', index_filter, type_filter,
                                                                SourceFilter.from_json(partial_body))
                        if permitted is None:
                            raise PermissionError('You are not permitted to access any of the requested'
                                                  ' stored fields in group "{0}".'.format(partial))
                        elif permitted:
                            partial_body = {
                                'include': [str(p) for p in permitted.includes],
                                'exclude': [str(p) for p in permitted.excludes]
                            }

                        partial_fields[partial] = partial_body

                    if partial_fields != json['partial_fields']:
                        json['partial_fields'] = partial_fields
                        json_updated = True

            if inspect_source:
                if json is not None and '_source' in json:
                    requested_source = SourceFilter.from_json(json['_source'])

                source_filter = client.create_source_filter('api/search/documents', index_filter,
                                                            type_filter, requested_source)
                if source_filter is None:
                    raise PermissionError('You are not permitted to access any of the requested source fields.')
                elif json is not None and source_filter:
                    json['_source'] = source_filter.as_json()
                    source_filter = None
                    json_updated = True
            else:
                source_filter = requested_source
        else:
            source_filter = requested_source

        if json is not None:
            if json.get('query'):
                query = QueryDslParser()
                query.query(json['query'])
                self._inspect_parser(client, query, index_filter, type_filter)

            aggregation_keyword = next((k for k in reversed(json) if k in ['aggregations', 'aggs']), None)
            if aggregation_keyword is not None and json.get(aggregation_keyword):
                aggregations = AggregationParser()
                aggregations.aggregations(json[aggregation_keyword])
                if self._inspect_parser(client, aggregations, index_filter, type_filter):
                    json_updated = True

            if json.get('highlight'):
                highlight = HighlightParser()
                highlight.parse(json['highlight'])
                self._inspect_parser(client, highlight, index_filter, type_filter)

            if json.get('post_filter'):
                post_filter = QueryDslParser()
                post_filter.filter(json['post_filter'])
                self._inspect_parser(client, post_filter, index_filter, type_filter)

            if json.get('rescore'):
                try:
                    rescores = [json['rescore']['query']]
                except IndexError:
                    rescores = [rescore['query'] for rescore in json['rescore']]

                for rescore in rescores:
                    query = QueryDslParser()
                    query.query(rescore['rescore_query'])
                    self._inspect_parser(client, query, index_filter, type_filter)

        return index_filter, type_filter, source_filter, json if json_updated else None

    def _check_permission(self, permission, client, index_filter, type_filter=None, fields=None):
        if index_filter:
            forbidden = []
            for index in index_filter.iter_patterns():
                if type_filter:
                    for document_type in type_filter.iter_patterns():
                        if fields:
                            for field in fields:
                                if not client.can(permission, index, document_type, field):
                                    forbidden.append('/'.join((str(index), str(document_type), str(field))))
                        elif not client.can(permission, index, document_type):
                            forbidden.append('/'.join((str(index), str(document_type))))
                elif not client.can(permission, index):
                    forbidden.append(str(index))

            if forbidden:
                scope = 'fields' if fields else 'types' if type_filter else 'indices'
                raise PermissionError(self._permission_errors[permission][scope].format(', '.join(forbidden)))
        elif not client.can(permission):
            raise PermissionError(self._permission_errors[permission]['cluster'])

    def _inspect_parser(self, client, parser, index_filter, type_filter):
        json_updated = False
        for permission, index, document_type, field in parser.permissions:
            if permission != 'api/feature/queryString':
                indices = index_filter if index is None else FilterString.from_string(index)
                types = type_filter if document_type is None else FilterString.from_string(document_type)
                self._check_permission(permission, client, indices, types, None if field is None else [field])
            elif client.has_restriction(index or index_filter, document_type or type_filter):
                # TODO: Remove this once we've got a parser for query strings!
                raise PermissionError(
                    'You are restricted to specific fields and as such cannot utilize the query string search.')

        if client.is_restricted('indices'):
            for index in parser.indices:
                if not index_filter.matches(FilterString.from_string(index)):
                    raise RequestError(400, 'Index filter "{0}" does not match the requested scope "{1}".'
                                            ''.format(index, index_filter))

        if client.is_restricted('types'):
            for index, document_type in parser.documents:
                if index and not index_filter.matches(FilterString.from_string(index)):
                    raise RequestError(400, 'Index filter "{0}" does not match the requested scope "{1}".'
                                            ''.format(index, index_filter))
                elif not type_filter.matches(FilterString.from_string(document_type)):
                    raise RequestError(400, 'Type filter "{0}" does not match the requested scope "{1}".'
                                            ''.format(document_type, type_filter))

        if client.is_restricted('fields'):
            for index, document_type, field in parser.fields:
                if index:
                    indices = FilterString.from_string(index)
                    if not index_filter.matches(indices):
                        raise RequestError(400, 'Index filter "{0}" does not match the requested scope "{1}".'
                                                ''.format(index, index_filter))
                else:
                    indices = index_filter

                if document_type:
                    types = FilterString.from_string(document_type)
                    if not type_filter.matches(types):
                        raise RequestError(400, 'Type filter "{0}" does not match the requested scope "{1}".'
                                                ''.format(document_type, type_filter))
                else:
                    types = type_filter

                for index in indices.iter_patterns():
                    for document_type in types.iter_patterns():
                        if not client.can('api/search/documents', index, document_type, field):
                            raise PermissionError('You are not permitted to search for documents of type "{0}" in index'
                                                  ' "{1}" by using field "{2}".'.format(document_type, index, field))

            try:
                document_requests = parser.document_requests
            except AttributeError:
                pass
            else:
                for index, document_type, document_request in document_requests:
                    if index and not index_filter.matches(FilterString.from_string(index)):
                        raise RequestError(400, 'Index filter "{0}" does not match the requested scope "{1}".'
                                                ''.format(index, index_filter))
                    elif document_type and not type_filter.matches(FilterString.from_string(document_type)):
                        raise RequestError(400, 'Type filter "{0}" does not match the requested scope "{1}".'
                                                ''.format(document_type, type_filter))

                    requested_source = SourceFilter.from_json(document_request.get('_source'))
                    source_filter = client.create_source_filter('api/search/documents', index_filter,
                                                                type_filter, requested_source)
                    if source_filter is None:
                        raise PermissionError('You are either not permitted to access the document type'
                                              ' "{0}" or any of the requested fields ({1}) in index "{2}".'
                                              ''.format(document_type or type_filter, requested_source,
                                                        index or index_filter))
                    elif source_filter:
                        document_request['_source'] = source_filter.as_json()
                        json_updated = True

                    if 'fielddata_fields' in document_request:
                        requested_fielddata = FieldsFilter.from_json(document_request['fielddata_fields'])
                        fielddata_filter = client.create_fields_filter('api/search/documents', index_filter,
                                                                       type_filter, requested_fielddata)
                        if fielddata_filter is None:
                            raise PermissionError(
                                'You are not permitted to access any of the requested fielddata fields ({0}) of type'
                                ' "{1}" in index "{2}".'.format(requested_fielddata, document_type or type_filter,
                                                                index or index_filter))
                        elif fielddata_filter:
                            document_request['fielddata_fields'] = fielddata_filter.as_json()
                            json_updated = True

        return json_updated


class SearchTemplateApiRequest(ElasticRequest):
    locations = {
        'GET': [
            '/_search/template',
            '/_search/template/{identifier}'
        ],
        'POST': [
            '/_search/template',
            '/_search/template/{identifier}'
        ],
        'DELETE': '/_search/template/{identifier}'
    }

    @Permission('api/search/templates')
    def inspect(self, client):
        pass


class SearchShardsApiRequest(ElasticRequest):
    before = 'GetIndexApiRequest'
    locations = {
        'GET': '/{indices}/_search_shards',
        'POST': '/{indices}/_search_shards'
    }

    @Permission('api/search/shards')
    def inspect(self, client):
        pass


class SuggestApiRequest(ElasticRequest):
    locations = {
        'GET': '/_suggest',
        'POST': '/_suggest'
    }

    @Permission('api/search/suggest')
    def inspect(self, client):
        pass


class MultiSearchApiRequest(SearchApiRequest):
    _errors = None

    before = [
        'GetIndexApiRequest',
        'IndexApiRequest',
        'GetApiRequest'
    ]

    locations = {
        'GET': [
            '/_msearch',
            '/{indices}/_msearch',
            '/{indices}/{documents}/_msearch'
        ],
        'POST': [
            '/_msearch',
            '/{indices}/_msearch',
            '/{indices}/{documents}/_msearch'
        ]
    }

    @Permission('api/bulk', scope='cluster')
    def inspect(self, client):
        lines, self._errors = [], []
        for i, (header, body) in enumerate(self._parse_payload()):
            try:
                index_filter, type_filter, _, json = self.inspect_request(
                    client, FilterString.from_list(header['index']),
                    FilterString.from_list(header['type']), json=body)
            except RequestError as error:
                self._errors.append((i, {
                    'status': error.status_code,
                    'error': '[{0}] {1}'.format(APP_NAME, error.reason)
                }))
            else:
                header['index'] = [str(part) for part in index_filter]
                header['type'] = [str(part) for part in type_filter]
                lines.append(self.json_encode(header))
                lines.append(self.json_encode(json or body))

        if not lines:
            response = ElasticResponse()
            response.content = self.json_encode({'responses': [e for p, e in self._errors]},
                                                not self.query.is_false('pretty'))
            response.headers['Content-Length'] = str(len(response.content))
            response.headers['Content-Type'] = 'application/json'
            response.status_code = 200
            del self._errors
            return response

        self.path = '/_msearch'  # We're enforcing headers with indices and types where applicable
        self.body = '\n'.join(lines) + '\n'

    def transform(self, stream, chunk_size):
        if not self._errors:
            return stream

        return self._transform_payload(''.join(stream), chunk_size)

    def _parse_payload(self):
        default_indices = self.get_match('indices', '').split(',')
        default_types = self.get_match('documents', '').split(',')

        with closing(StringIO(self.body)) as feed:
            header, line, line_no = None, feed.readline(), 1
            while line:
                if header is None:
                    header = line.strip()
                else:
                    body = line.strip()
                    if not body:
                        raise RequestError(
                            400, 'Expected body at line #{0}. Got an empty line instead.'.format(line_no))

                    try:
                        header = self.json_decode(header) if header else {}
                        if not header.get('index'):
                            header['index'] = default_indices
                        elif isinstance(header['index'], basestring):
                            header['index'] = [header['index']]
                        elif not isinstance(header['index'], list):
                            raise RequestError(400, 'Failed to parse header at line #{0}. List or string'
                                                    ' expected for key "index". Got type "{1}" instead.'
                                                    ''.format(line_no - 1, type(header['index'])))

                        if not header.get('type'):
                            header['type'] = default_types
                        elif isinstance(header['type'], basestring):
                            header['type'] = [header['type']]
                        elif not isinstance(header['type'], list):
                            raise RequestError(400, 'Failed to parse header at line #{0}. List or string'
                                                    ' expected for key "type". Got type "{1}" instead.'
                                                    ''.format(line_no - 1, type(header['type'])))
                    except ValueError as error:
                        raise RequestError(
                            400, 'Failed to decode JSON header at line #{0}: {1}'.format(line_no - 1, error))
                    except AttributeError:
                        raise RequestError(
                            400, 'Failed to parse header at line #{0}. Invalid JSON object.'.format(line_no - 1))

                    try:
                        yield header, self.json_decode(body)
                    except ValueError as error:
                        raise RequestError(400, 'Failed to decode JSON body at line #{0}: {1}'.format(line_no, error))
                    else:
                        header = None

                line_no += 1
                line = feed.readline()

    def _transform_payload(self, payload, chunk_size):
        try:
            data = self.json_decode(payload)
        except ValueError:
            pass
        else:
            for position, error in self._errors:
                data['responses'].insert(position, error)

            payload = self.json_encode(data, not self.query.is_false('pretty'))
            if 'Content-Length' in self.context.response.headers:
                self.context.response.headers['Content-Length'] = str(len(payload))

        while payload:
            yield payload[:chunk_size]
            payload = payload[chunk_size:]


class CountApiRequest(SearchApiRequest):
    before = [
        'GetIndexApiRequest',
        'IndexApiRequest',
        'GetApiRequest'
    ]

    locations = {
        'GET': [
            '/_count',
            '/{indices}/_count',
            '/{indices}/{documents}/_count'
        ],
        'POST': [
            '/_count',
            '/{indices}/_count',
            '/{indices}/{documents}/_count'
        ]
    }

    def inspect(self, client):
        index_filter, type_filter, _, json = self.inspect_request(
            client, FilterString.from_string(self.get_match('indices', '')),
            FilterString.from_string(self.get_match('documents', '')), json=self.json)

        if self.query.last('q', '').strip() and self.query.last('q').strip() != '*':
            if client.has_restriction(index_filter, type_filter):
                # TODO: Provide a more sophisticated solution once we've got a parser for query strings!
                raise PermissionError(
                    'You are restricted to specific fields and as such cannot utilize the query string search.')

        if index_filter:
            if type_filter:
                self.path = '/{0}/{1}/_count'.format(index_filter, type_filter)
            else:
                self.path = '/{0}/_count'.format(index_filter)

        if json is not None:
            self.body = self.json_encode(json)


class SearchExistsApiRequest(ElasticRequest):
    locations = {
        'GET': [
            '/_search/exists',
            '/{indices}/_search/exists',
            '/{indices}/{documents}/_search/exists'
        ],
        'POST': [
            '/_search/exists',
            '/{indices}/_search/exists',
            '/{indices}/{documents}/_search/exists'
        ]
    }

    @Permission('api/feature/notImplemented')
    @Permission('api/search/documents')
    def inspect(self, client):
        pass


class ValidateApiRequest(SearchApiRequest):
    locations = {
        'GET': [
            '/_validate/query',
            '/{indices}/_validate/query',
            '/{indices}/{documents}/_validate/query'
        ],
        'POST': [
            '/_validate/query',
            '/{indices}/_validate/query',
            '/{indices}/{documents}/_validate/query',
            '/(?P<indices>\.kibana)/(?P<documents>__kibanaQueryValidator)/_validate/query'
        ]
    }

    def inspect(self, client):
        if '__kibanaQueryValidator' in self.path:
            # I have _still_ no explanation for this. Please enlighten
            # me if you think this is security relevant in any way.
            if client.can('api/search/explain', '.kibana'):
                return

            raise PermissionError(self._permission_errors['api/search/explain']['indices'].format('.kibana'))

        index_filter, type_filter, _, json = self.inspect_request(
            client, FilterString.from_string(self.get_match('indices', '')),
            FilterString.from_string(self.get_match('documents', '')), json=self.json)

        if self.query.last('q', '').strip() and self.query.last('q').strip() != '*':
            if client.has_restriction(index_filter, type_filter):
                # TODO: Provide a more sophisticated solution once we've got a parser for query strings!
                raise PermissionError(
                    'You are restricted to specific fields and as such cannot utilize the query string search.')

        if not self.query.is_false('explain'):
            self._check_permission('api/search/explain', client, index_filter, type_filter)

        if index_filter:
            if type_filter:
                self.path = '/{0}/{1}/_validate/query'.format(index_filter, type_filter)
            else:
                self.path = '/{0}/_validate/query'.format(index_filter)

        if json is not None:
            self.body = self.json_encode(json)


class ExplainApiRequest(ElasticRequest):
    locations = {
        'GET': '/{index}/{document}/{identifier}/_explain',
        'POST': '/{index}/{document}/{identifier}/_explain'
    }

    @Permission('api/feature/notImplemented')
    @Permission('api/search/explain')
    def inspect(self, client):
        pass


class PercolateApiRequest(ElasticRequest):
    before = [
        'IndexApiRequest',
        'GetApiRequest'
    ]

    locations = {
        'GET': [
            '/{index}/{document}/_percolate',
            '/{index}/{document}/{identifier}/_percolate'
        ],
        'POST': [
            '/{index}/{document}/_percolate',
            '/{index}/{document}/{identifier}/_percolate'
        ]
    }

    @Permission('api/search/percolate')
    def inspect(self, client):
        pass


class MultiPercolateApiRequest(ElasticRequest):
    before = [
        'GetIndexApiRequest',
        'IndexApiRequest',
        'GetApiRequest'
    ]

    locations = {
        'GET': [
            '/_mpercolate',
            '/{index}/_mpercolate',
            '/{index}/{document}/_mpercolate'
        ],
        'POST': [
            '/_mpercolate',
            '/{index}/_mpercolate',
            '/{index}/{document}/_mpercolate'
        ]
    }

    @Permission('api/bulk', scope='cluster')
    @Permission('api/search/percolate')
    def inspect(self, client):
        pass


class MoreLikeThisApiRequest(ElasticRequest):
    locations = {
        'GET': '/{index}/{document}/{identifier}/_mlt'
    }

    @Permission('api/feature/deprecated', scope='cluster')
    @Permission('api/feature/moreLikeThis')
    def inspect(self, client):
        pass


class FieldStatsApiRequest(ElasticRequest):
    before = 'GetIndexApiRequest'
    locations = {
        'GET': '/{indices}/_field_stats'
    }

    @Permission('api/search/fieldStats')
    def inspect(self, client):
        pass
