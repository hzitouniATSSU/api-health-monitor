import asyncio
import logging

from app.services.scheduler import scheduler_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def main() -> None:
    logging.info("Starting monitoring worker")
    asyncio.run(scheduler_loop())


if __name__ == "__main__":
    main()