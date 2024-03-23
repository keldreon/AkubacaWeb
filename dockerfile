FROM python:3.10

RUN mkdir /code
WORKDIR /code
ADD . /code/
COPY requirements.txt requirements.txt
RUN pip3 install -r requirements.txt
EXPOSE 8080
CMD ["python",  "/code/rub_waitress_serv.py"]