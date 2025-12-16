import sqlite3


db_path = "data/scholar.db"
try:
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    cur.execute(
        """
        update papers
        SET processed = 0,
            processed_at = NULL,
            processing_error = NULL
        """
    )
    con.commit()
    print(f"Reset {cur.rowcount} papers")

except sqlite3.Error as error:
    print("Error: ", error)

finally:
    cur.close()
    con.close()
