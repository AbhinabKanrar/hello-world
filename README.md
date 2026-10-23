# Cohuvo

- make install
- make models

cohuvo population build --audience examples/audience.yaml --seed 42 --out out/personas.json1

cohuvo graph build --personas out/personas.json1 --seed 42 --out-dir out/graph

cohuvo sim run --personas out/personas.json1 --graph out/graph --scenario examples/scenario.yaml --seed 42 --out-dir out/sim

cohuvo report build --personas out/personas.json1 --graph out/graph --sim out/sim --scenario examples/scenario.yaml --seed 42 --out-dir out/report