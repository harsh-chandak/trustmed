FROM rasa/rasa:3.6.10

COPY . /app
WORKDIR /app

USER root
RUN pip install neo4j

USER 1001
