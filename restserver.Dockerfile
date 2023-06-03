FROM python:3.11
RUN pip install flask
RUN pip install reportlab
COPY rest rest
CMD ["python3", "rest/server.py"]