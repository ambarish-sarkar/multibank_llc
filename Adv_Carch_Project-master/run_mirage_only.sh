#!/bin/bash
set -e
cd "/home/ambarish-sarkar/IITH/Thesis/multi-bank_llc_simulator/Adv_Carch_Project-master/Mirage_cache_occupancy"

echo "Running region0 attack for 100/0 split"
sed -i 's/region-split-ratio=.*/region-split-ratio=1/g' config.ini
sed -i 's/attack-mode=.*/attack-mode=region0/g' config.ini
python3 main.py &
sleep 1

echo "Running region0 attack for 30/70 split"
sed -i 's/region-split-ratio=.*/region-split-ratio=0.3/g' config.ini
sed -i 's/attack-mode=.*/attack-mode=region0/g' config.ini
python3 main.py &
sleep 1

echo "Running region0 attack for 50/50 split"
sed -i 's/region-split-ratio=.*/region-split-ratio=0.5/g' config.ini
sed -i 's/attack-mode=.*/attack-mode=region0/g' config.ini
python3 main.py &
sleep 1

echo "Running simultaneous attack for 50/50 split"
sed -i 's/region-split-ratio=.*/region-split-ratio=0.5/g' config.ini
sed -i 's/attack-mode=.*/attack-mode=simultaneous/g' config.ini
python3 main.py &
sleep 1

wait
echo "Mirage runs complete."
