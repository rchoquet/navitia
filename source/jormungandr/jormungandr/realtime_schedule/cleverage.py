# coding=utf-8

# Copyright (c) 2001-2016, Canal TP and/or its affiliates. All rights reserved.
#
# This file is part of Navitia,
#     the software to build cool stuff with public transport.
#
# Hope you'll enjoy and contribute to this project,
#     powered by Canal TP (www.canaltp.fr).
# Help us simplify mobility and open public transport:
#     a non ending quest to the responsive locomotion way of traveling!
#
# LICENCE: This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#
# Stay tuned using
# twitter @navitia
# IRC #navitia on freenode
# https://groups.google.com/d/forum/navitia
# www.navitia.io
from jormungandr.realtime_schedule.realtime_proxy import RealtimeProxy
from flask import logging
import pybreaker
import pytz
import requests as requests
from jormungandr import cache, app
from jormungandr.schedule import RealTimePassage
from datetime import datetime


class Cleverage(RealtimeProxy):
    """
    class managing calls to cleverage external service providing real-time next passages
    """
    def __init__(self, id, service_url, service_args, timezone, object_id_tag=None,
                 destination_id_tag=None, instance=None, timeout=10, **kwargs):
        self.service_url = service_url if (service_url[-1] == u'/') else (service_url+'/')
        self.service_args = service_args
        self.timeout = timeout  # timeout in seconds
        self.rt_system_id = id
        self.object_id_tag = object_id_tag if object_id_tag else id
        self.destination_id_tag = destination_id_tag
        self.instance = instance
        self.breaker = pybreaker.CircuitBreaker(fail_max=app.config['CIRCUIT_BREAKER_MAX_CLEVERAGE_FAIL'],
                                                reset_timeout=app.config['CIRCUIT_BREAKER_CLEVERAGE_TIMEOUT_S'])
        self.timezone = pytz.timezone(timezone)

    def __repr__(self):
        """
         used as the cache key. we use the rt_system_id to share the cache between servers in production
        """
        return self.rt_system_id

    @cache.memoize(app.config['CACHE_CONFIGURATION'].get('TIMEOUT_CLEVERAGE', 30))
    def _call_cleverage(self, url):
        """
        http call to cleverage
        """
        logging.getLogger(__name__).debug('Cleverage RT service , call url : {}'.format(url))
        try:
            return self.breaker.call(requests.get, url, timeout=self.timeout, headers=self.service_args)
        except pybreaker.CircuitBreakerError as e:
            logging.getLogger(__name__).error('Cleverage RT service dead, using base '
                                              'schedule (error: {}'.format(e))
        except requests.Timeout as t:
            logging.getLogger(__name__).error('Cleverage RT service timeout, using base '
                                              'schedule (error: {}'.format(t))
        except:
            logging.getLogger(__name__).exception('Cleverage RT error, using base schedule')
        return None

    def _make_url(self, route_point):
        """
        The url returns something like a departure on a stop point
        """

        stop_id = route_point.fetch_stop_id(self.object_id_tag)

        if not stop_id:
            # one a the id is missing, we'll not find any realtime
            logging.getLogger(__name__).debug('missing realtime id for {obj}: stop code={s}'.
                                              format(obj=route_point, s=stop_id))
            return None

        url = "{base_url}{stop_id}".format(base_url=self.service_url, stop_id=stop_id)

        return url

    def _get_dt(self, datetime_str):
        dt = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")

        utc_dt = self.timezone.normalize(self.timezone.localize(dt)).astimezone(pytz.utc)

        return utc_dt

    def _get_passages(self, route_point, cleverage_resp):
        logging.getLogger(__name__).debug('cleverage response: {}'.format(cleverage_resp))

        line_code = route_point.fetch_line_code()

        schedules = next((line['schedules'] for line in cleverage_resp if line['code'].lower() == line_code.lower()), None)

        if schedules:
            next_passages = []
            for next_expected_st in schedules:
                # for the moment we handle only the NextStop and the direction
                dt = self._get_dt(next_expected_st['departure'])
                direction = next_expected_st.get('destination_name')
                is_real_time = next_expected_st.get('realtime') == '1'
                next_passage = RealTimePassage(dt, direction, is_real_time)
                next_passages.append(next_passage)

            return next_passages
        else:
            return None

    def _get_next_passage_for_route_point(self, route_point, count=None, from_dt=None, current_dt=None):
        url = self._make_url(route_point)
        if not url:
            return None
        r = self._call_cleverage(url)
        if not r:
            return None

        if r.status_code != 200:
            # TODO better error handling, the response might be in 200 but in error
            logging.getLogger(__name__).error('Cleverage RT service unavailable, impossible to query : {}'
                                              .format(r.url))
            return None

        return self._get_passages(route_point, r.json())

    def status(self):
        return {'id': self.rt_system_id,
                'timeout': self.timeout,
                'circuit_breaker': {'current_state': self.breaker.current_state,
                                    'fail_counter': self.breaker.fail_counter,
                                    'reset_timeout': self.breaker.reset_timeout},
                }
