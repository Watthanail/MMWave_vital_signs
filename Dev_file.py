import numpy as np
import pandas as pd

def read_dca1000(file_name):
    # Sensor config
    num_adcsamples = 64  # number of ADC samples per chirp
    num_adcbits = 16      # number of ADC bits per sample
    num_rx = 4            # number of receivers
    num_lanes = 2         # number of lanes is always 2
    is_real = 0           # set to 1 if real only data, 0 if complex data

    # Read .bin file
    with open(file_name, 'rb') as f:
        adc_data = np.fromfile(f, dtype=np.int16)

    # If 12 or 14 bits ADC per sample compensate for sign extension
    if num_adcbits != 16:
        l_max = 2**(num_adcbits - 1) - 1
        adc_data[adc_data > l_max] = adc_data[adc_data > l_max] - 2**num_adcbits

    file_size = adc_data.size

    if is_real:
        num_chirps = file_size // (num_adcsamples * num_rx)
        lvds = adc_data.reshape((num_chirps, num_adcsamples * num_rx))
    else:
        num_chirps = file_size // (2 * num_adcsamples * num_rx)
        lvds = np.zeros(file_size // 2, dtype=np.complex64)

        real_part = adc_data[0:file_size:4] + 1j * adc_data[2:file_size:4]
        imag_part = adc_data[1:file_size:4] + 1j * adc_data[3:file_size:4]
        lvds[:len(real_part)] = real_part
        lvds[len(real_part):] = imag_part

        lvds = lvds.reshape((num_chirps, num_adcsamples * num_rx))

    adc_data = np.zeros((num_rx, num_chirps * num_adcsamples), dtype=np.complex64)
    for row in range(num_rx):
        for i in range(num_chirps):
            adc_data[row, i * num_adcsamples: (i + 1) * num_adcsamples] = lvds[i, row * num_adcsamples: (row + 1) * num_adcsamples]

    return adc_data

# Example usage
file_name = r'D:\MMwave_openradar\GUI_config\300724\2129adc_data.bin'
adc_data = read_dca1000(file_name)

# Convert the data to a pandas DataFrame and print it
adc_data_df = pd.DataFrame(adc_data)
print(adc_data_df)
