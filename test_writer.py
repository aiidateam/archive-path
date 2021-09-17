import contextlib
from io import BytesIO
import json
from pathlib import Path
import shelve
import shutil
import sys
import tempfile
from typing import Any, BinaryIO, Dict, Iterator, List, Type, Union
import zipfile

from aiida import orm as aiida_orm
from aiida.orm.implementation.sqlalchemy.querybuilder import SqlaQueryBuilder
from sqlalchemy import (
    JSON,
    String,
    Text,
    create_engine,
    event,
    func,
    insert,
    orm,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.sql.schema import Table

sys.path.insert(0, "/DbUsers/chrisjsewell/Documents/GitHub/archive-path/")

from archive_path import NOTSET, ZipPath, extract_file_in_zip, read_file_in_zip


class SqliteModel:
    """Represent a row in an sqlite database table"""

    def __repr__(self) -> str:
        """Return a representaiton of the row columns"""
        string = f"<{self.__class__.__name__}"
        for col in self.__table__.columns:
            # don't include columns with potentially large values
            if isinstance(col.type, (JSON, Text)):
                continue
            string += f" {col.name}={getattr(self, col.name)}"
        return string + ">"


Base = orm.declarative_base(cls=SqliteModel, name="SqliteModel")


def pg_to_sqlite(table: Table):
    """Convert a model intended for PostGreSQL to one compatible with SQLite"""
    new = table.tometadata(Base.metadata)
    for column in new.columns:
        if isinstance(column.type, UUID):
            column.type = String()
        elif isinstance(column.type, JSONB):
            column.type = JSON()
    return new


def create_orm_cls(name: str, tbl_name: str) -> Base:
    """Create and ORM class from an existing table in the declarative meta"""
    return type(
        name,
        (Base,),
        {
            "__tablename__": tbl_name,
            "__table__": Base.metadata.tables[tbl_name],
            **{
                col.name if col.name != "metadata" else "_metadata": col
                for col in Base.metadata.tables[tbl_name].columns
            },
        },
    )


# we need to import all models, to ensure they are loaded on the metadata
from aiida.backends.sqlalchemy.models import (
    authinfo,
    base,
    comment,
    computer,
    group,
    log,
    node,
    user,
)

for table in base.Base.metadata.sorted_tables:
    pg_to_sqlite(table)


DbUser = create_orm_cls("DbUser", "db_dbuser")
DbAuthInfo = create_orm_cls("DbAuthInfo", "db_dbauthinfo")
DbGroup = create_orm_cls("DbGroup", "db_dbgroup")
DbNode = create_orm_cls("DbNode", "db_dbnode")
DbComment = create_orm_cls("DbComment", "db_dbcomment")
DbComputer = create_orm_cls("DbComputer", "db_dbcomputer")
DbLog = create_orm_cls("DbLog", "db_dblog")
DbLink = create_orm_cls("DbLink", "db_dblink")
DbGroupNodes = create_orm_cls("DbGroupNodes", "db_dbgroup_dbnodes")


def sqlite_enforce_foreign_keys(dbapi_connection, _):
    """Enforce foreign key constraints, when using sqlite backend (off by default)"""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.close()


class ArchiveWriter:

    _meta_name = "_metadata.json"
    _db_name = "_db.sqlite"

    def __init__(self, zip_path, *, mode="x", work_dir=None, debug=False):
        assert mode in ("a", "w", "x")
        self._zip_mode = mode
        self._zip_file = Path(zip_path)
        self._init_work_dir = work_dir
        self._in_temp = False
        self._in_context = False
        self._debug = debug
        self._central_dir = self._zip_path = self._work_dir = self._conn = None

    def assert_in_context(self):
        if not self._in_context:
            raise AssertionError("Not in context")

    def __enter__(self):
        """Start writing to the archive"""
        self._metadata = {}
        if self._init_work_dir is not None:
            self._work_dir = Path(self._init_work_dir)
            self._in_temp = False
        else:
            self._work_dir = Path(tempfile.mkdtemp())
            self._in_temp = True
        self._central_dir = shelve.open(str(self._work_dir / "central_dir"))
        self._zip_path = ZipPath(
            self._zip_file,
            mode=self._zip_mode,
            name_to_info=self._central_dir,
            write_first=(self._db_name, self._meta_name),
        )
        engine = create_engine(
            f"sqlite:///{self._work_dir / self._db_name}", future=True, echo=self._debug
        )
        event.listen(engine, "connect", sqlite_enforce_foreign_keys)
        Base.metadata.create_all(engine)
        self._conn = engine.connect()
        self._in_context = True
        return self

    def __exit__(self, *args, **kwargs):
        """Finalise the archive"""
        self._conn.close()
        # TODO if compress smaller file, but then slower to extract
        # test size with/without (also maybe vacuum before storing)
        with (self._work_dir / self._db_name).open("rb") as handle:
            self.stream_binary(self._db_name, handle)
        # the metadata is small, so no benefit for compression
        self.stream_binary(
            self._meta_name,
            BytesIO(json.dumps(self._metadata).encode("utf8")),
            compression=zipfile.ZIP_STORED,
        )
        self._zip_path.close()
        self._central_dir.close()
        if self._in_temp:
            shutil.rmtree(self._work_dir, ignore_errors=False)
        self._central_dir = self._zip_path = self._work_dir = self._conn = None
        self._in_context = False

    def update_metadata(self, data: Dict[str, Any]) -> None:
        """Add key, values to the top-level metadata."""
        self._metadata.update(data)

    def insert_rows(
        self, orm_cls: Type[Base], data: List[Dict[str, Any]], commit: bool = True
    ) -> None:
        """Add multiple rows to a database table in the archive."""
        # TODO these do not fail if a non-existent column is given (silently dropped)
        self.assert_in_context()
        self._conn.execute(insert(orm_cls.__table__), data)
        if commit:
            self._conn.commit()

    def get_row_count(self) -> Dict[str, int]:
        """Return a count of rows for all tables."""
        data = {}
        for name, table in Base.metadata.tables.items():
            result = self._conn.execute(
                select(func.count()).select_from(table)
            ).scalar()
            data[name] = result
        return data

    def stream_binary(
        self,
        name: str,
        handle: BinaryIO,
        *,
        buffer_size=None,
        compression=NOTSET,
        level=NOTSET,
        comment=NOTSET,
    ) -> None:
        """Add a binary stream to the archive.

        :param compression: the ZIP compression method to use when writing the archive,
                if not set use the default value,
                ZIP_STORED (no compression), ZIP_DEFLATED (requires zlib),
                ZIP_BZIP2 (requires bz2) or ZIP_LZMA (requires lzma).
        :param level: control the compression level to use when writing files to the archive
                When using ZIP_DEFLATED integers 0 through 9 are accepted.
                When using ZIP_BZIP2 integers 1 through 9 are accepted.
        :param comment: A binary comment, stored in the central directory
        """
        self.assert_in_context()
        with self._zip_path.joinpath(name).open(
            "wb", compression=compression, level=level, comment=comment
        ) as zip_handle:
            shutil.copyfileobj(handle, zip_handle, buffer_size)

    def get_file_count(self) -> int:
        """Return number of files in the archive"""
        return len(self._central_dir)


def extract_metadata(path: Union[str, Path]) -> Dict[str, Any]:
    """Extract the metadata dictionary from the archive"""
    # TODO fail if not the first record in central directory
    # so we don't have to iter all files to fail
    return json.loads(read_file_in_zip(path, ArchiveWriter._meta_name, "utf8"))


def extract_db(
    zip_path: Union[str, Path], out_path: Union[None, str, Path] = None
) -> Path:
    """Extract the entity database from the archive"""
    # TODO fail if not the second record in central directory
    # so we don't have to iter all files to fail
    if out_path is None:
        out_path = Path.cwd() / ArchiveWriter._db_name
    out_path = Path(out_path)
    with out_path.open("wb") as handle:
        extract_file_in_zip(zip_path, ArchiveWriter._db_name, handle)
    return out_path


@contextlib.contextmanager
def archive_db_session(path: Union[str, Path]) -> Iterator[orm.Session]:
    """Access a database session for the archive.

    The database will first be extracted to a temporary directory
    """
    with tempfile.TemporaryDirectory() as workdir:
        db_path = Path(workdir) / "db.sqlite"
        extract_db(path, db_path)
        engine = create_engine(f"sqlite:///{db_path}", future=True)
        with orm.Session(engine) as session:
            yield session


class ArchiveQueryBuilder(SqlaQueryBuilder):
    """Archive query builder"""

    @property
    def Node(self):
        return DbNode

    @property
    def Link(self):
        return DbLink

    @property
    def Computer(self):
        return DbComputer

    @property
    def User(self):
        return DbUser

    @property
    def Group(self):
        return DbGroup

    @property
    def AuthInfo(self):
        return DbAuthInfo

    @property
    def Comment(self):
        return DbComment

    @property
    def Log(self):
        return DbLog

    @property
    def table_groups_nodes(self):
        return DbGroupNodes.__table__


@contextlib.contextmanager
def archive_querybuilder(path: Union[str, Path]) -> Iterator[aiida_orm.QueryBuilder]:
    """Access a database session for the archive.

    The database will first be extracted to a temporary directory
    """
    with tempfile.TemporaryDirectory() as workdir:
        db_path = Path(workdir) / "db.sqlite"
        extract_db(path, db_path)
        engine = create_engine(f"sqlite:///{db_path}", future=True)
        with orm.Session(engine) as session:
            from aiida.orm.implementation.backends import Backend as _BackendCls

            # TODO currently class checked against Backend
            # may be better to check against Protocol

            class _BackendQueryBuilder(_BackendCls):
                def get_session(self):
                    return session

                def get_backend_entity(self, res):
                    # TODO db model -> backend entity
                    if isinstance(res, SqliteModel):
                        raise NotImplementedError("projecting orm classes from archive")
                    return res

                # required (but unneeded) abstract methods
                def authinfos(self):
                    pass

                def comments(self):
                    pass

                def computers(self):
                    pass

                def groups(self):
                    pass

                def logs(self):
                    pass

                def migrate(self):
                    pass

                def nodes(self):
                    pass

                def query(self):
                    pass

                def transaction(self):
                    pass

                def users(self):
                    pass

            backend_qb = ArchiveQueryBuilder(_BackendQueryBuilder())

            class _Backend:
                def query(self):
                    return backend_qb

            qb = aiida_orm.QueryBuilder(_Backend())
            yield qb


with ArchiveWriter("test.zip", mode="w", debug=False) as writer:
    writer.update_metadata({"aiida_version": 2, "db_schema_version": 1})
    writer.stream_binary("tester3", BytesIO(b"hallo"), compression=zipfile.ZIP_STORED)
    writer.stream_binary("tester4", BytesIO(b"hallo"), comment=b"a comment")
    writer.insert_rows(DbUser, [{"id": 1, "email": "bob"}, {"id": 2, "email": "bill"}])
    writer.insert_rows(DbComputer, [{"label": "bebop"}])
    writer.insert_rows(
        DbNode,
        [
            {"id": 1, "user_id": 1, "node_type": ""},
            {"id": 2, "user_id": 1, "node_type": ""},
        ],
    )
    writer.update_metadata({"db_rows": writer.get_row_count()})
    writer.update_metadata({"file_count": writer.get_file_count()})


print(extract_metadata("test.zip"))

with archive_db_session("test.zip") as session:
    print(session.execute(select(DbUser).where(DbUser.email == "bob")).scalars().all())
    print(session.execute(select(DbComputer)).scalars().all())
    print(session.execute(select(DbUser.id, DbNode.id).join(DbNode)).all())

with archive_querybuilder("test.zip") as qb:
    print(
        qb.append(aiida_orm.Node, project="**", filters={"id": 1})
        .append(aiida_orm.User, project="email")
        .dict()
    )
