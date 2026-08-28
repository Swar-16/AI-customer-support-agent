from sqlalchemy import create_engine, text

from packages.config.settings import get_settings


settings = get_settings("test")
url = settings.database_url

print("Environment: test")
print("Host:", url.host)
print("Port:", url.port)
print("Username:", url.username)
# print("Database:", url.path)
print("Password configured:", url.password is not None)
print(
    "Password length:",
    len(url.password) if url.password else 0,
)

engine = create_engine(str(url))

with engine.connect() as connection:
    row = connection.execute(
        text(
            """
            SELECT
                current_database(),
                current_user
            """
        )
    ).one()

    print("Connected:", row)