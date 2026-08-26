import psycopg2

passwords = ["postgres", "admin", "password", "root", "123456", ""]
connected = False
for pwd in passwords:
    try:
        conn = psycopg2.connect(dbname="postgres", user="postgres", password=pwd, host="localhost", port=5432)
        print(f"Connected successfully with password: '{pwd}'")
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SELECT 1;")
        print("Test query SELECT 1 passed!")
        # Create test database if not exists
        cur.execute("SELECT 1 FROM pg_database WHERE datname = 'recoverx_staging';")
        if not cur.fetchone():
            cur.execute("CREATE DATABASE recoverx_staging;")
            print("Database recoverx_staging created!")
        else:
            print("Database recoverx_staging already exists!")
        cur.close()
        conn.close()
        connected = True
        break
    except Exception as e:
        print(f"Password '{pwd}' failed: {e}")

if not connected:
    print("PostgreSQL local server requires authentication setup or is running with custom credentials.")

