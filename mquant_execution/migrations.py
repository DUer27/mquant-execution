from .db import Database

def migrate(path='runtime/paper.db'):
    db=Database(path); db.migrate(); return db
