# hello-world

- make install
- make models

society population build --audience examples/audience.yaml --seed 42 --out out/personas.json1

society graph build --personas out/personas.json1 --seed 42 --out-dir out/graph

society sim run --personas out/personas.json1 --graph out/graph --scenario examples/scenario.yaml --seed 42 --out-dir out/sim

society report build --personas out/personas.json1 --graph out/graph --sim out/sim --scenario examples/scenario.yaml --seed 42 --out-dir out/report