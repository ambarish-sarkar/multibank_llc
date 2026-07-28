#!/bin/bash

NUM_TRIALS=100

# common.py's get_trial_addresses() also hardcodes a single trial and is
# shared by every design below - patch it once here, otherwise main.py will
# raise KeyError as soon as trial reaches 1 (trial_addresses only has key 0).
sed -i "s/for trial in range(.*):/for trial in range(${NUM_TRIALS}):/g" common.py

echo "Running Mirage Cache Occupancy..."
cd Mirage_cache_occupancy || exit
sed -i "s/for trial in range(.*):/for trial in range(${NUM_TRIALS}):/g" main.py

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

cd ..



echo "Running Ceaser Cache Occupancy..."
cd Ceaser_cache_occupancy || exit
sed -i "s/for trial in range(.*):/for trial in range(${NUM_TRIALS}):/g" main.py

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

cd ..




echo "Running Ceaser-s Cache Occupancy..."
cd Ceaser-s_cache_occupancy || exit
sed -i "s/for trial in range(.*):/for trial in range(${NUM_TRIALS}):/g" main.py

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

wait

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

cd ..

echo "Running ScatterCache Cache Occupancy..."
cd ScatterCache_cache_occupancy || exit
sed -i "s/for trial in range(.*):/for trial in range(${NUM_TRIALS}):/g" main.py

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
cd ..

echo "Running Normal Cache Occupancy..."
cd Normal_cache_occupancy || exit
sed -i "s/for trial in range(.*):/for trial in range(${NUM_TRIALS}):/g" main.py

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
cd ..

echo "Waiting for all tasks to finish..."
wait

echo "Generating covert-channel diff plots..."
python3 plot_diffs.py

echo "All scripts executed successfully."

