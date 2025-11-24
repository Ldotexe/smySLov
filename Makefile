include .env

run:
	sudo make up
	pipenv run python3 main.py

up:
	sudo docker run --name smyslov_game_bot-db -e POSTGRES_PASSWORD=$(POSTGRES_PASSWORD) -p 5432:5432 -d postgres

down:
	sudo docker stop smyslov_game_bot-db
	sudo docker rm smyslov_game_bot-db

rerun:
	sudo make down
	make run