"""모든 수집처가 공통으로 쓰는 공고 레코드."""
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Optional


@dataclass
class Notice:
    source: str            # 청약홈 / LH / SH / 청년안심
    uid: str               # 수집처 안에서 유일한 id (중복·재알림 판단용)
    title: str
    category: str = ""     # 원천 유형명 (행복주택, 매입임대주택, APT 민영 …)
    region: str = ""       # 시도 (서울, 경기 …)
    address: str = ""
    posted: Optional[date] = None     # 공고 게시일
    begin: Optional[date] = None      # 접수 시작
    end: Optional[date] = None        # 접수 마감
    announce: Optional[date] = None   # 당첨/발표일
    households: str = ""
    url: str = ""
    status: str = ""       # 원천이 주는 상태 (모집중, 접수마감 …)
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.uid}"

    @property
    def text(self) -> str:
        """판정용으로 제목·유형을 합친 문자열."""
        return f"{self.title} {self.category}"

    def is_closed(self, today: date) -> bool:
        if self.end is not None:
            return self.end < today
        if self.status and any(k in self.status for k in ("마감", "완료", "종료")):
            return True
        # 마감일을 모르는 공고(SH·청년안심): 발표일이 지났거나 접수 시작 후 7일이 지나면 종료로 본다
        if self.announce is not None and self.announce < today:
            return True
        if self.begin is not None and (today - self.begin).days > 7:
            return True
        # 접수일 정보가 전혀 없으면(SH 목록) 게시 후 21일이 지나면 접수가 끝난 것으로 본다
        # (SH는 보통 게시 2주 뒤 접수, 상태는 발표 때까지 '모집중'으로 남는다)
        if self.begin is None and self.posted is not None and (today - self.posted).days > 21:
            return True
        return False

    def to_dict(self):
        d = asdict(self)
        for k in ("posted", "begin", "end", "announce"):
            d[k] = d[k].isoformat() if d[k] else None
        return d
