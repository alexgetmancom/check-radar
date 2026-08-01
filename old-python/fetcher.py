from database.connection import init_db
from services.fns_api import sync_receipts_from_fns


def main():
    init_db()
    sync_receipts_from_fns()


if __name__ == "__main__":
    main()
