.PHONY: test up down logs smoke scale clean

test:            ## run unit tests locally
	python3 -m unittest -v

up:              ## build and start nginx + 3 app replicas + redis
	docker compose up -d --build --wait

down:
	docker compose down

logs:
	docker compose logs -f --tail=50

smoke:           ## hit the stack and show which replica answered
	./scripts/smoke.sh

scale:           ## make scale N=5
	docker compose up -d --scale app=$(N) --wait

clean:
	docker compose down -v --rmi local
