# Cohuvo

- make install

Lab grown meat:

cohuvo population build --audience examples/audience.yaml --seed 42 --out out/personas.jsonl

cohuvo graph build --personas out/personas.jsonl --seed 42 --out-dir out/graph

cohuvo sim run --personas out/personas.jsonl --graph out/graph --scenario examples/scenario.yaml --seed 42 --out-dir out/sim

cohuvo report build --personas out/personas.jsonl --graph out/graph --sim out/sim --scenario examples/scenario.yaml --seed 42 --out-dir out/report

Netflix:

cohuvo population build \
  --audience examples/netflix-ads/audience.yaml \
  --seed 42 --out out/netflix-ads/personas.jsonl

cohuvo graph build \
  --personas out/netflix-ads/personas.jsonl \
  --seed 42 --out-dir out/netflix-ads/graph

cohuvo sim run \
  --personas out/netflix-ads/personas.jsonl \
  --graph out/netflix-ads/graph \
  --scenario examples/netflix-ads/scenario.yaml \
  --seed 42 --out-dir out/netflix-ads/sim

cohuvo report build \
  --personas out/netflix-ads/personas.jsonl \
  --graph out/netflix-ads/graph \
  --sim out/netflix-ads/sim \
  --scenario examples/netflix-ads/scenario.yaml \
  --seed 42 --out-dir out/netflix-ads/report


cohuvo survey run \
  --audience examples/lam-meat/audience.yaml \
  --scenario examples/lam-meat/scenario.yaml \
  --seed 42 \
  --out-dir out/lab-grown-meat