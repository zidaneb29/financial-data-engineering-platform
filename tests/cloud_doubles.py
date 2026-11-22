"""In-memory service doubles for protocol and transaction failure tests."""

import copy
import io


class ServiceError(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__("synthetic service failure")


class MemoryS3:
    def __init__(self):
        self.objects = {}
        self.puts = []
        self.gets = []
        self.fail_key = None
        self.failures = 0
        self.corrupt_put = False
        self.interrupt_ready = False

    def get_object(self, *, Bucket, Key):
        self.gets.append(Key)
        if (Bucket, Key) not in self.objects:
            raise ServiceError("NoSuchKey")
        return {"Body": io.BytesIO(self.objects[Bucket, Key]), "ETag": "deliberately-not-an-md5"}

    def put_object(self, *, Bucket, Key, Body, IfNoneMatch, ChecksumSHA256, ServerSideEncryption):
        import base64
        import hashlib

        assert IfNoneMatch == "*" and ServerSideEncryption == "AES256"
        assert ChecksumSHA256 == base64.b64encode(hashlib.sha256(Body).digest()).decode()
        if self.failures and (self.fail_key is None or self.fail_key in Key):
            self.failures -= 1
            raise ServiceError("ServiceUnavailable")
        if (Bucket, Key) in self.objects:
            raise ServiceError("PreconditionFailed")
        self.objects[Bucket, Key] = b"corrupt" if self.corrupt_put else Body
        self.puts.append(Key)
        if self.interrupt_ready and "/ready/" in Key:
            self.interrupt_ready = False
            raise KeyboardInterrupt
        return {"ETag": "multipart-style-test-double"}


class MemoryWarehouse:
    def __init__(self):
        self.tables = {}
        self.sql = []
        self.fail_table = None
        self.ambiguous_commit = False
        self.connects = 0
        self.mutex_rows = 1

    def connect(self):
        self.connects += 1
        return MemoryConnection(self)


class MemoryConnection:
    def __init__(self, database):
        self.database = database
        self.tables = None

    def cursor(self):
        return MemoryCursor(self)

    def commit(self):
        self.database.tables = copy.deepcopy(self.tables)
        self.tables = None
        if self.database.ambiguous_commit:
            self.database.ambiguous_commit = False
            raise RuntimeError("injected commit response loss")

    def rollback(self):
        self.tables = None

    def close(self):
        pass


class MemoryCursor:
    def __init__(self, connection):
        self.connection = connection
        self.results = []
        self.rowcount = 0

    def execute(self, sql, params=()):
        db = self.connection.database
        db.sql.append(sql)
        if sql == "BEGIN TRANSACTION":
            self.connection.tables = copy.deepcopy(db.tables)
            return
        tables = self.connection.tables
        assert tables is not None, "DML must be inside a transaction"
        if sql.startswith("UPDATE OPS.LOAD_MUTEX"):
            self.rowcount = db.mutex_rows
        elif sql.startswith("SELECT MANIFEST_HASH"):
            self.results = [
                (row["MANIFEST_HASH"], row["RECEIPT_HASH"], row["COUNTS_TEXT"])
                for row in tables.get("OPS.BATCH_LOAD", []) if row["BATCH_ID"] == params[0]
            ]
        elif sql.startswith("SELECT COUNT(*)"):
            table = sql.split()[3]
            self.results = [(sum(row["BATCH_ID"] == params[0] for row in tables.get(table, [])),)]
        elif sql.startswith("SELECT SHA256, PAYLOAD_TEXT"):
            self.results = [
                (row["SHA256"], row["PAYLOAD_TEXT"])
                for row in tables.get("RAW.SOURCE_OBJECT", []) if row["OBJECT_ID"] == params[0]
            ]
        elif sql.startswith("MERGE INTO RAW.SOURCE_OBJECT"):
            records = tables.setdefault("RAW.SOURCE_OBJECT", [])
            if not any(row["OBJECT_ID"] == params[0] for row in records):
                records.append(dict(zip(("OBJECT_ID", "OBJECT_KEY", "SHA256", "PAYLOAD_TEXT"), params, strict=True)))
        elif sql.startswith("INSERT INTO "):
            table = sql.split()[2]
            if db.fail_table == table:
                db.fail_table = None
                raise RuntimeError("injected warehouse DML failure")
            columns = sql[sql.index("(") + 1:sql.index(")")].replace(" ", "").split(",")
            for start in range(0, len(params), len(columns)):
                row = dict(zip(columns, params[start:start + len(columns)], strict=True))
                tables.setdefault(table, []).append(row)
        else:
            raise AssertionError(f"Unexpected SQL in transaction double: {sql}")

    def fetchall(self):
        return self.results

    def fetchone(self):
        return self.results[0]

    def close(self):
        pass
