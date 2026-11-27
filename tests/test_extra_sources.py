import unittest
from datetime import date
from unittest.mock import Mock, patch

from cheong.sources import social


class SocialHousingTest(unittest.TestCase):
    def test_vacant_buildings_include_operator_detail_link(self):
        example = {
            "homeCode": "20000568",
            "homeName": "[사회주택] 세운 예시",
            "adres": "서울 중구 예시로 123",
            "statusCnt": 2,
            "houseType": "원룸(오픈형)",
            "homeDetail": "화장실, 주방시설이 포함된 7평 원룸입니다.",
            "regDate": 1741571594000,
        }
        notice = social.to_notice(example)
        self.assertEqual((notice.source, notice.uid, notice.title), ("사회주택", "20000568", "세운 예시"))
        self.assertEqual((notice.region, notice.households), ("서울", "2"))
        self.assertEqual(notice.url, f"{social.BASE}view.do?menuNo=300006&homeCode=20000568")
        self.assertIsNone(notice.posted)  # 건물 등록일을 모집공고일로 해석하지 않는다.
        self.assertIsNone(notice.end)
        self.assertIsNone(social.to_notice({**example, "statusCnt": 0}))
        self.assertIsNone(social.to_notice({**example, "houseType": "원룸(셰어형)"}))
        self.assertIsNone(social.to_notice({**example, "houseType": "쓰리룸", "homeDetail": "방 외 시설을 공유하는 셰어하우스"}))
        self.assertIsNone(social.to_notice({**example, "homeDetail": "공용 주방 및 전용 화장실"}))
        self.assertIsNotNone(social.to_notice({**example, "homeDetail": "개별 주방과 전용 욕실"}))

    def test_stops_on_first_empty_page_and_keeps_vacancies(self):
        example = {"homeCode": "1", "homeName": "예시 주택", "statusCnt": 1,
                   "houseType": "원룸(분리형)", "homeDetail": "개별 주방과 개별 화장실"}
        pages = [Mock(**{"json.return_value": {"resultList": rows, "maxpage": 9}})
                 for rows in ([example], [example, {**example, "homeCode": "2"}], [])]
        with patch.object(social, "get", side_effect=pages) as get:
            notices = social.fetch({}, date(2026, 11, 27))

        self.assertEqual([notice.uid for notice in notices], ["1", "2"])
        self.assertEqual([call.args[1] for call in get.call_args_list], [
            {"pageNum": 1, "rowCount": 30, "searchSil": "Y"},
            {"pageNum": 2, "rowCount": 30, "searchSil": "Y"},
            {"pageNum": 3, "rowCount": 30, "searchSil": "Y"},
        ])
