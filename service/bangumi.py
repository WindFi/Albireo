# -*- coding: utf-8 -*-
from sqlalchemy.orm.exc import NoResultFound

from domain.Episode import Episode
from domain.Bangumi import Bangumi
from domain.Favorites import Favorites
from domain.WatchProgress import WatchProgress
from domain.TorrentFile import TorrentFile
from domain.VideoFile import VideoFile
from datetime import datetime, timedelta
from utils.SessionManager import SessionManager
from utils.exceptions import ClientError
from utils.http import json_resp
from utils.db import row2dict
from sqlalchemy.sql.expression import or_, desc, asc
from sqlalchemy.sql import select, func, distinct
from sqlalchemy.orm import joinedload, subqueryload
import json
from service.common import utils

import logging

logger = logging.getLogger(__name__)


class BangumiService:

    def recent_update(self, days):

        current = datetime.now()

        # from one week ago
        start_time = current - timedelta(days=days)

        session = SessionManager.Session()
        try:
            result = session.query(Episode, Bangumi).\
                join(Bangumi).\
                filter(Episode.delete_mark == None).\
                filter(Episode.status == Episode.STATUS_DOWNLOADED).\
                filter(Episode.update_time >= start_time).\
                filter(Episode.update_time <= current).\
                order_by(desc(Episode.update_time))

            episode_list = []

            for eps, bgm in result:
                episode = row2dict(eps)
                episode['thumbnail'] = utils.generate_thumbnail_link(eps, bgm)
                episode['bangumi'] = row2dict(bgm)
                episode['bangumi']['cover'] = utils.generate_cover_link(bgm)
                episode_list.append(episode)

            return json_resp({'data': episode_list})
        finally:
            SessionManager.Session.remove()

    def episode_detail(self, episode_id, user_id):
        session = SessionManager.Session()
        try:
            (episode, bangumi) = session.query(Episode, Bangumi).\
                join(Bangumi).\
                options(joinedload(Bangumi.cover_image)).\
                options(joinedload(Episode.thumbnail_image)).\
                filter(Episode.delete_mark == None).\
                filter(Episode.id == episode_id).\
                one()
            watch_progress = session.query(WatchProgress).\
                filter(WatchProgress.episode_id == episode_id).\
                filter(WatchProgress.user_id == user_id).\
                first()

            episode_dict = row2dict(episode)
            episode_dict['bangumi'] = row2dict(bangumi)
            episode_dict['bangumi']['cover'] = utils.generate_cover_link(bangumi)
            utils.process_bangumi_dict(bangumi, episode_dict['bangumi'])
            episode_dict['thumbnail'] = utils.generate_thumbnail_link(episode, bangumi)
            utils.process_episode_dict(episode, episode_dict)

            if watch_progress is not None:
                episode_dict['watch_progress'] = row2dict(watch_progress)

            if episode.status == Episode.STATUS_DOWNLOADED:
                episode_dict['video_files'] = []
                video_file_list = session.query(VideoFile).filter(VideoFile.episode_id == episode_id).all()
                for video_file in video_file_list:
                    video_file_dict = row2dict(video_file)
                    video_file_dict['url'] = utils.generate_video_link(str(bangumi.id), video_file.file_path)
                    episode_dict['video_files'].append(video_file_dict)

            return json_resp(episode_dict)
        except NoResultFound:
            raise ClientError(ClientError.NOT_FOUND, 404)
        finally:
            SessionManager.Session.remove()

    def on_air_bangumi(self, user_id, type):
        session = SessionManager.Session()
        current_day = datetime.today()
        start_time = datetime(current_day.year, current_day.month, 1)
        if current_day.month == 12:
            next_year = current_day.year + 1
            next_month = 1
        else:
            next_year = current_day.year
            next_month = current_day.month + 1
        end_time = datetime(next_year, next_month, 1)

        try:
            result = session.query(distinct(Episode.bangumi_id), Bangumi).\
                join(Bangumi). \
                options(joinedload(Bangumi.cover_image)).\
                filter(Bangumi.delete_mark == None). \
                filter(Bangumi.type == type).\
                filter(Episode.airdate >= start_time).\
                filter(Episode.airdate <= end_time)

            bangumi_list = []
            bangumi_id_list = [bangumi_id for bangumi_id, bangumi in result]

            if len(bangumi_id_list) == 0:
                return json_resp({'data': []})

            favorites = session.query(Favorites).\
                filter(Favorites.bangumi_id.in_(bangumi_id_list)).\
                filter(Favorites.user_id == user_id).\
                all()

            for bangumi_id, bangumi in result:
                bangumi_dict = row2dict(bangumi)
                bangumi_dict['cover'] = utils.generate_cover_link(bangumi)
                utils.process_bangumi_dict(bangumi, bangumi_dict)
                for fav in favorites:
                    if fav.bangumi_id == bangumi_id:
                        bangumi_dict['favorite_status'] = fav.status
                        break
                bangumi_list.append(bangumi_dict)

            return json_resp({'data': bangumi_list})
        finally:
            SessionManager.Session.remove()

    def list_bangumi(self, page, count, sort_field, sort_order, name, user_id, bangumi_type):
        try:

            session = SessionManager.Session()
            query_object = session.query(Bangumi).\
                options(joinedload(Bangumi.cover_image)).\
                filter(Bangumi.delete_mark == None)

            if bangumi_type != -1:
                query_object = query_object.filter(Bangumi.type == bangumi_type)

            if name is not None:
                name_pattern = '%{0}%'.format(name.encode('utf-8'),)
                logger.debug(name_pattern)
                query_object = query_object.\
                    filter(or_(Bangumi.name.ilike(name_pattern), Bangumi.name_cn.ilike(name_pattern)))
                # count total rows
                total = session.query(func.count(Bangumi.id)).\
                    filter(or_(Bangumi.name.ilike(name_pattern), Bangumi.name_cn.ilike(name_pattern))).\
                    scalar()
            else:
                total = session.query(func.count(Bangumi.id)).scalar()

            if sort_order == 'desc':
                query_object = query_object.\
                    order_by(desc(getattr(Bangumi, sort_field)))

            else:
                query_object = query_object.\
                    order_by(asc(getattr(Bangumi, sort_field)))

            if count == -1:
                bangumi_list = query_object.all()
            else:
                offset = (page - 1) * count
                bangumi_list = query_object.offset(offset).limit(count).all()

            bangumi_id_list = [bgm.id for bgm in bangumi_list]

            favorites = session.query(Favorites).\
                filter(Favorites.bangumi_id.in_(bangumi_id_list)).\
                filter(Favorites.user_id == user_id).\
                all()

            bangumi_dict_list = []
            for bgm in bangumi_list:
                bangumi = row2dict(bgm)
                bangumi['cover'] = utils.generate_cover_link(bgm)
                utils.process_bangumi_dict(bgm, bangumi)
                for fav in favorites:
                    if fav.bangumi_id == bgm.id:
                        bangumi['favorite_status'] = fav.status
                bangumi_dict_list.append(bangumi)

            return json_resp({'data': bangumi_dict_list, 'total': total})
        finally:
            SessionManager.Session.remove()

    def get_bangumi(self, id, user_id):
        try:
            session = SessionManager.Session()

            bangumi = session.query(Bangumi).\
                options(joinedload(Bangumi.episodes).joinedload(Episode.thumbnail_image)).\
                options(joinedload(Bangumi.cover_image)).\
                filter(Bangumi.delete_mark == None).\
                filter(Bangumi.id == id).\
                one()

            favorite = session.query(Favorites).\
                filter(Favorites.bangumi_id == id).\
                filter(Favorites.user_id == user_id).\
                first()

            watch_progress_list = session.query(WatchProgress).\
                filter(WatchProgress.bangumi_id == bangumi.id).\
                filter(WatchProgress.user_id == user_id).\
                all()

            episodes = []

            watch_progress_hash_table = {}
            for watch_progress in watch_progress_list:
                watch_progress_dict = row2dict(watch_progress)
                watch_progress_hash_table[watch_progress.episode_id] = watch_progress_dict

            for episode in bangumi.episodes:
                if episode.delete_mark is not None:
                    continue
                eps = row2dict(episode)
                eps['thumbnail'] = utils.generate_thumbnail_link(episode, bangumi)
                utils.process_episode_dict(episode, eps)
                if episode.id in watch_progress_hash_table:
                    eps['watch_progress'] = watch_progress_hash_table[episode.id]
                episodes.append(eps)

            bangumi_dict = row2dict(bangumi)

            if favorite is not None:
                bangumi_dict['favorite_status'] = favorite.status

            bangumi_dict['episodes'] = episodes

            bangumi_dict['cover'] = utils.generate_cover_link(bangumi)
            utils.process_bangumi_dict(bangumi, bangumi_dict)

            return json_resp({'data': bangumi_dict})
        except NoResultFound:
            raise ClientError(ClientError.NOT_FOUND, 404)
        finally:
            SessionManager.Session.remove()

bangumi_service = BangumiService()
