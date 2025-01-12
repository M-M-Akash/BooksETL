
#dag - directed acyclic graph

#tasks : 1) fetch amazon data (extract) 2) clean data (transform) 3) create and store data in table on postgres (load)
#operators : Python Operator and PostgresOperator
#hooks - allows connection to postgres
#dependencies

from datetime import datetime, timedelta
from airflow import DAG
import requests
import pandas as pd
from bs4 import BeautifulSoup
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.operators.postgres import PostgresOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)




def get_data_books(ti):
    # Base URL of the Amazon search results for data science books
    extracted_books = []
    seen_titles = set()
    # URL to scrape
    url = "https://books.toscrape.com/catalogue/category/books/travel_2/index.html"

# Send a GET request to the URL
    response = requests.get(url)

# Check if the request was successful
    if response.status_code == 200:
        # Parse the HTML content with BeautifulSoup
        soup = BeautifulSoup(response.content, 'html.parser')

        # Find all books on the page
        books = soup.find_all('article', class_='product_pod')

        # Loop through each book and extract details
        for book in books:
            # Extract the title
            title = book.h3.a['title']

            # Extract the price
            price = book.find('p', class_='price_color').text

            # Extract the rating
            rating_class = book.find('p', class_='star-rating')['class']
            rating = rating_class[1] if len(rating_class) > 1 else 'No rating'
                
            if title and price and rating:
                book_title = title.strip()
                extracted_books.append({
                    "Title": book_title,
                    "Price": price.strip(),
                    "Rating": rating.strip(),
                })
    
        # Increment the page number for the next iteration
    else:
        print("Failed to retrieve the page")

    # Limit to the requested number of books
    
    # Convert the list of dictionaries into a DataFrame
    df = pd.DataFrame(extracted_books)
    
    # Remove duplicates based on 'Title' column
    df.drop_duplicates(subset="Title", inplace=True)
    
    # Push the DataFrame to XCom
    ti.xcom_push(key='book_data', value=df.to_dict('records'))

#3) create and store data in table on postgres (load)
    
def insert_book_data_into_postgres(ti):
    book_data = ti.xcom_pull(key='book_data', task_ids='fetch_book_data')
    if not book_data:
        raise ValueError("No book data found")

    postgres_hook = PostgresHook(postgres_conn_id='books_connection')
    insert_query = """
    INSERT INTO books (title, price, rating)
    VALUES (%s, %s, %s)
    ON CONFLICT (title) DO NOTHING; -- Skip duplicates
    """
    for book in book_data:
        postgres_hook.run(insert_query, parameters=(book['Title'], book['Price'], book['Rating']))
        logger.info(f"Inserted book: {book['Title']}")


default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2025, 1, 12),
    'retries': 2,
    'retry_delay': timedelta(minutes=1),
}

dag = DAG(
    'fetch_and_store_books',
    default_args=default_args,
    description='A simple DAG to fetch book data from Amazon and store it in Postgres',
    schedule_interval=timedelta(days=1),
)

#operators : Python Operator and PostgresOperator
#hooks - allows connection to postgres


fetch_book_data_task = PythonOperator(
    task_id='fetch_book_data',
    python_callable=get_data_books,
    dag=dag,
)

create_table_task = PostgresOperator(
    task_id='create_table',
    postgres_conn_id='books_connection',
    sql="""
    CREATE TABLE IF NOT EXISTS books (
        id SERIAL PRIMARY KEY,
        title TEXT NOT NULL UNIQUE,
        price TEXT,
        rating TEXT
    );
    """,
    dag=dag,
)

insert_book_data_task = PythonOperator(
    task_id='insert_book_data',
    python_callable=insert_book_data_into_postgres,
    dag=dag,
)

#dependencies

fetch_book_data_task >> create_table_task >> insert_book_data_task
