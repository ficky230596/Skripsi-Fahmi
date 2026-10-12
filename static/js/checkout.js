let map = null;
let marker = null;

// Status alamat yang sedang dipilih.
let isPrimaryAddress = false;
let isSavedAddress = false;

// Mencegah perubahan lokasi ketika alamat tersimpan sedang dimuat.
let isSettingSavedAddress = false;


/* =========================================================
   INISIALISASI PETA
========================================================= */

function initMap(lat, lng) {
    if (!window.L) return;

    const mapElement = document.getElementById('map');

    if (!mapElement) return;

    const initialLat = Number.isFinite(Number(lat))
        ? Number(lat)
        : 1.3;

    const initialLng = Number.isFinite(Number(lng))
        ? Number(lng)
        : 124.8;

    // Jangan membuat peta Leaflet lebih dari satu kali.
    if (!map) {
        map = L.map('map').setView(
            [initialLat, initialLng],
            13
        );

        L.tileLayer(
            'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
            {
                maxZoom: 19,
                attribution: '© OpenStreetMap'
            }
        ).addTo(map);

        // Klik peta hanya diizinkan untuk alamat baru.
        map.on('click', function (e) {
            if (isPrimaryAddress || isSavedAddress) {
                return;
            }

            setPoint(
                e.latlng.lat,
                e.latlng.lng
            );
        });
    } else {
        map.setView(
            [initialLat, initialLng],
            13
        );
    }

    // Marker tidak dapat diseret langsung.
    if (marker) {
        marker.setLatLng([
            initialLat,
            initialLng
        ]);
    } else {
        marker = L.marker(
            [initialLat, initialLng],
            {
                draggable: false
            }
        ).addTo(map);
    }

    updateMapInteraction();
}


/* =========================================================
   MENGATUR STATUS INTERAKSI PETA
========================================================= */

function updateMapInteraction() {
    if (!map) return;

    const canChooseLocation =
        !isPrimaryAddress &&
        !isSavedAddress;

    if (canChooseLocation) {
        map.dragging.enable();
        map.scrollWheelZoom.enable();
        map.doubleClickZoom.enable();
        map.touchZoom.enable();
        map.boxZoom.enable();
        map.keyboard.enable();
    } else {
        map.dragging.disable();
        map.scrollWheelZoom.disable();
        map.doubleClickZoom.disable();
        map.touchZoom.disable();
        map.boxZoom.disable();
        map.keyboard.disable();
    }

    // Marker selalu dipindahkan melalui klik peta,
    // bukan dengan menyeret marker.
    if (marker && marker.dragging) {
        marker.dragging.disable();
    }

    const mapElement = document.getElementById('map');

    if (mapElement) {
        mapElement.style.cursor = canChooseLocation
            ? 'crosshair'
            : 'not-allowed';
    }
}


/* =========================================================
   MODE ALAMAT
========================================================= */

function setSavedAddressMode(isPrimary, hasSavedAddress) {
    isPrimaryAddress = Boolean(isPrimary);
    isSavedAddress = Boolean(hasSavedAddress);

    updateMapInteraction();
}


/* =========================================================
   MEMILIH KOORDINAT ALAMAT TERSIMPAN
========================================================= */

function setSavedPoint(lat, lng) {
    lat = Number(lat);
    lng = Number(lng);

    if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
        return;
    }

    isSettingSavedAddress = true;

    if (!map) {
        initMap(lat, lng);
    } else {
        map.setView([lat, lng], 16);

        if (marker) {
            marker.setLatLng([lat, lng]);
        } else {
            marker = L.marker(
                [lat, lng],
                {
                    draggable: false
                }
            ).addTo(map);
        }
    }

    const latitudeField =
        document.getElementById('latitude');

    const longitudeField =
        document.getElementById('longitude');

    if (latitudeField) {
        latitudeField.value = lat;
    }

    if (longitudeField) {
        longitudeField.value = lng;
    }

    updateMapInteraction();

    // Hitung jarak dan ongkir untuk koordinat alamat terpilih.
    calculateDelivery(lat, lng);

    isSettingSavedAddress = false;
}


/* =========================================================
   MEMILIH LOKASI BARU MELALUI PETA
========================================================= */

function setPoint(lat, lng) {
    // Jangan izinkan perubahan koordinat alamat tersimpan.
    if (isPrimaryAddress || isSavedAddress) {
        return;
    }

    lat = Number(lat);
    lng = Number(lng);

    if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
        return;
    }

    if (!map) {
        initMap(lat, lng);
    }

    if (marker) {
        marker.setLatLng([lat, lng]);
    } else {
        marker = L.marker(
            [lat, lng],
            {
                draggable: false
            }
        ).addTo(map);
    }

    const latitudeField =
        document.getElementById('latitude');

    const longitudeField =
        document.getElementById('longitude');

    const addressField =
        document.getElementById('address');

    if (latitudeField) {
        latitudeField.value = lat;
    }

    if (longitudeField) {
        longitudeField.value = lng;
    }

    if (addressField) {
        addressField.value =
            `Lokasi terpilih: ${lat.toFixed(6)}, ${lng.toFixed(6)}`;
    }

    updateMapInteraction();

    calculateDelivery(lat, lng);
}


/* =========================================================
   PERHITUNGAN JARAK DAN ONGKIR
========================================================= */

function calculateDelivery(lat, lng) {
    const distanceField =
        document.getElementById('distance_km');

    const distanceText =
        document.getElementById('distanceText');

    const feeText =
        document.getElementById('feeText');

    const marketLat = Number(window.MARKET_LAT);
    const marketLng = Number(window.MARKET_LNG);
    const baseFee = Number(window.BASE_FEE);
    const perKm = Number(window.PER_KM);

    if (
        !Number.isFinite(marketLat) ||
        !Number.isFinite(marketLng) ||
        !Number.isFinite(baseFee) ||
        !Number.isFinite(perKm)
    ) {
        console.error(
            'Konfigurasi lokasi pasar atau ongkir tidak valid.'
        );

        return;
    }

    const url =
        'https://router.project-osrm.org/route/v1/driving/' +
        `${marketLng},${marketLat};${lng},${lat}` +
        '?overview=false';

    fetch(url)
        .then(function (response) {
            if (!response.ok) {
                throw new Error(
                    'Gagal mengambil data rute pengantaran.'
                );
            }

            return response.json();
        })
        .then(function (data) {
            if (!data.routes || !data.routes[0]) {
                throw new Error(
                    'Rute pengantaran tidak ditemukan.'
                );
            }

            // Abaikan hasil perhitungan lama apabila
            // pengguna sudah memilih koordinat yang berbeda.
            const currentLat = Number(
                document.getElementById('latitude')?.value
            );

            const currentLng = Number(
                document.getElementById('longitude')?.value
            );

            if (
                currentLat !== lat ||
                currentLng !== lng
            ) {
                return;
            }

            const km =
                data.routes[0].distance / 1000;

            const fee =
                baseFee + Math.ceil(km * perKm);

            if (distanceField) {
                distanceField.value = km.toFixed(2);
            }

            if (distanceText) {
                distanceText.textContent =
                    km.toFixed(2) + ' km';
            }

            if (feeText) {
                feeText.textContent =
                    'Rp ' + fee.toLocaleString('id-ID');
            }
        })
        .catch(function (error) {
            console.error(
                'Kesalahan perhitungan ongkir:',
                error
            );
        });
}


/* =========================================================
   METODE PENGANTARAN
========================================================= */

function toggleDelivery() {
    const selectedMethod = document.querySelector(
        'input[name="delivery_method"]:checked'
    );

    if (!selectedMethod) return;

    const isDelivery =
        selectedMethod.value === 'delivery';

    const deliveryBox =
        document.getElementById('deliveryBox');

    const pickupInfo =
        document.getElementById('pickupInfo');

    if (deliveryBox) {
        deliveryBox.classList.toggle(
            'hidden',
            !isDelivery
        );
    }

    if (pickupInfo) {
        pickupInfo.classList.toggle(
            'hidden',
            isDelivery
        );
    }

    if (isDelivery) {
        if (!map) {
            initMap(
                Number(window.MARKET_LAT),
                Number(window.MARKET_LNG)
            );
        }

        if (map) {
            setTimeout(function () {
                map.invalidateSize();
            }, 100);
        }
    }

    updateMapInteraction();
}


/* =========================================================
   EKSPOR FUNGSI UNTUK TEMPLATE CHECKOUT
========================================================= */

window.initMap = initMap;
window.setPoint = setPoint;
window.setSavedPoint = setSavedPoint;
window.setSavedAddressMode = setSavedAddressMode;
window.toggleDelivery = toggleDelivery;
