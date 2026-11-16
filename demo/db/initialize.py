import os
import sys

import psycopg
from psycopg import sql

FIXTURES = [(1, "Notebook"), (2, "Pencil"), (3, "Folder")]


def initialize():
    with psycopg.connect(
        host="db",
        dbname="catalogue",
        user="catalogue_admin",
        password=os.environ["POSTGRES_PASSWORD"],
        connect_timeout=5,
        options="-c statement_timeout=10000 -c lock_timeout=5000",
    ) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS public.items ("
                           "id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
        for item in FIXTURES:
            connection.execute(
                "INSERT INTO public.items (id, name) VALUES (%s, %s) "
                "ON CONFLICT (id) DO NOTHING", item
            )
        exists = connection.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s", ("catalogue_reader",)
        ).fetchone()
        if not exists:
            connection.execute("CREATE ROLE catalogue_reader LOGIN")
        connection.execute(
            sql.SQL("ALTER ROLE catalogue_reader WITH LOGIN NOSUPERUSER "
                    "NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}")
            .format(sql.Literal(os.environ["APP_DB_PASSWORD"]))
        )
        connection.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        connection.execute("GRANT CONNECT ON DATABASE catalogue TO catalogue_reader")
        connection.execute("GRANT USAGE ON SCHEMA public TO catalogue_reader")
        connection.execute("GRANT SELECT ON public.items TO catalogue_reader")
        actual = connection.execute(
            "SELECT id, name FROM public.items WHERE id IN (1, 2, 3) ORDER BY id"
        ).fetchall()
        if actual != FIXTURES:
            raise ValueError("Existing fixture records differ; inspect them before continuing.")
    print("Database initialized; fixtures verified. Existing records were preserved.")


if __name__ == "__main__":
    try:
        initialize()
    except KeyError:
        print("Initialization configuration is incomplete. Check required environment "
              "variables without sharing their values.", file=sys.stderr)
        sys.exit(1)
    except ValueError:
        print("Existing fixture records differ from the expected data. "
              "Initialization was not completed; inspect the records before retrying.",
              file=sys.stderr)
        sys.exit(1)
    except psycopg.Error:
        print("Database initialization failed; completion could not be verified. "
              "Check database access and schema. A connection failure during commit "
              "can leave the commit outcome unknown; inspect before retrying.",
              file=sys.stderr)
        sys.exit(1)
