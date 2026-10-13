"""공고 수집처 모음. 각 모듈은 fetch(cfg) -> list[Notice] 를 제공한다."""
from . import applyhome, lh, sh, youth

ALL = {
    "applyhome": applyhome,  # 청약홈: 민영·공공 APT, 무순위, 오피스텔·민간임대
    "lh": lh,                # LH 임대·주거복지(매입임대, 든든전세 …)
    "sh": sh,                # SH 공공임대·분양 (서울주거포털)
    "youth": youth,          # 서울시 청년안심주택
}
