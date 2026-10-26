# Cohuvo

- make install
- make models

cohuvo population build --audience examples/audience.yaml --seed 42 --out out/personas.jsonl

cohuvo graph build --personas out/personas.jsonl --seed 42 --out-dir out/graph

cohuvo sim run --personas out/personas.jsonl --graph out/graph --scenario examples/scenario.yaml --seed 42 --out-dir out/sim

cohuvo report build --personas out/personas.jsonl --graph out/graph --sim out/sim --scenario examples/scenario.yaml --seed 42 --out-dir out/report

cohuvo survey run \
  --audience examples/audience.yaml \
  --scenario examples/scenario.yaml \
  --seed 42 \
  --out-dir out/lab-grown-meat