def calc_has_more(total: int, page: int, page_size: int) -> bool:
    return page * page_size < total
