"""Справочник регионов и городов России с кодами Wildberries.

Содержит структурированные данные о федеральных округах и городах России
с соответствующими кодами dest для API Wildberries.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class City:
    """Город с кодом dest для API Wildberries.

    Attributes:
        name: Название города.
        code: Уникальный код города (для внутреннего использования).
        dest: Код региона Wildberries для API запросов.
    """

    name: str
    code: str
    dest: int


@dataclass(frozen=True)
class District:
    """Федеральный округ РФ с городами.

    Attributes:
        name: Название федерального округа.
        code: Уникальный код округа.
        cities: Список городов в округе.
    """

    name: str
    code: str
    cities: list[City]


# Примечание: dest коды можно получать программно через WB geo API.
# Пока используем популярные города с заранее известными кодами.
DISTRICTS: list[District] = [
	District(
		name="Центральный",
		code="cfo",
		cities=[
			City(name="Москва", code="moskva", dest=-1257786),
			City(name="Санкт-Петербург", code="spb", dest=-1257801),
			City(name="Воронеж", code="voronezh", dest=-1257894),
			City(name="Нижний Новгород", code="nnov", dest=-1257788),
		],
	),
	District(
		name="Северо-Западный",
		code="szfo",
		cities=[
			City(name="Санкт-Петербург", code="spb", dest=-1257801),
			City(name="Калининград", code="kaliningrad", dest=-1257826),
			City(name="Архангельск", code="arhangelsk", dest=-1257822),
		],
	),
	District(
		name="Южный",
		code="ufo",
		cities=[
			City(name="Ростов-на-Дону", code="rostov", dest=-1257893),
			City(name="Краснодар", code="krasnodar", dest=-1257783),
			City(name="Волгоград", code="volgograd", dest=-1257891),
		],
	),
	District(
		name="Приволжский",
		code="pfo",
		cities=[
			City(name="Казань", code="kazan", dest=-1257787),
			City(name="Самара", code="samara", dest=-1257888),
			City(name="Пермь", code="perm", dest=-1257885),
		],
	),
	District(
		name="Уральский",
		code="urfo",
		cities=[
			City(name="Екатеринбург", code="ekb", dest=-1257876),
			City(name="Челябинск", code="chelyabinsk", dest=-1257874),
			City(name="Тюмень", code="tyumen", dest=-1257870),
		],
	),
	District(
		name="Сибирский",
		code="sfo",
		cities=[
			City(name="Новосибирск", code="novosibirsk", dest=-1257866),
			City(name="Красноярск", code="krasnoyarsk", dest=-1257862),
			City(name="Омск", code="omsk", dest=-1257864),
		],
	),
	District(
		name="Дальневосточный",
		code="dfo",
		cities=[
			City(name="Владивосток", code="vladivostok", dest=-1257853),
			City(name="Хабаровск", code="habarovsk", dest=-1257855),
			City(name="Якутск", code="yakutsk", dest=-1257852),
		],
	),
	District(
		name="Северо-Кавказский",
		code="skfo",
		cities=[
			City(name="Махачкала", code="mahachkala", dest=-1257898),
			City(name="Грозный", code="grozny", dest=-1257901),
			City(name="Ставрополь", code="stavropol", dest=-1257899),
		],
	),
]
