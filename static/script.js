document.addEventListener('DOMContentLoaded', () => {
    const state = {
        chart: null,
        currentAggregation: 'raw',
        flatpickrInstance: null
    };

    const elements = {
        chartContainer: document.getElementById('main-chart'),
        aggregationControls: document.querySelectorAll('input[name="aggregation"]'),
        datePickerContainer: document.getElementById('date-picker-container'),
        datePickerInput: document.getElementById('date-picker'),
        statusBadge: document.querySelector('.status-badge .status-text'),
        smaConnection: document.getElementById('sma-connection'),
        smaLastPoll: document.getElementById('sma-last-poll'),
        smaReadings: document.getElementById('sma-readings'),
        smaError: document.getElementById('sma-error')
    };

    // API Helpers
    async function fetchData(url) {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
    }

    // Update Status Badge
    async function updateStats() {
        try {
            const stats = await fetchData('/api/stats');
            if (stats && stats.total_readings !== undefined) {
                const count = stats.total_readings.toLocaleString();
                elements.statusBadge.textContent = `${count} readings`;
            }
        } catch (error) {
            console.error('Error fetching stats:', error);
        }
    }

    // Update SMA Status Panel
    async function updateSmaStatus() {
        try {
            const status = await fetchData('/api/sma-status');

            if (!status.configured) {
                elements.smaConnection.textContent = 'Not configured';
                elements.smaConnection.className = 'status-value status-warning';
                elements.smaLastPoll.textContent = '—';
                elements.smaReadings.textContent = '—';
                showSmaError('SMA_HOST and SMA_TOKEN not configured');
                return;
            }

            elements.smaConnection.textContent = status.connected ? 'Connected' : 'Disconnected';
            elements.smaConnection.className = status.connected
                ? 'status-value status-success'
                : 'status-value status-error';

            elements.smaLastPoll.textContent = status.last_poll
                ? new Date(status.last_poll).toLocaleTimeString()
                : '—';
            elements.smaReadings.textContent = status.total_readings.toLocaleString();

            if (status.last_error) {
                showSmaError(status.last_error);
            } else {
                clearSmaError();
            }
        } catch (error) {
            console.error('Error fetching SMA status:', error);
            elements.smaConnection.textContent = 'Error';
            elements.smaConnection.className = 'status-value status-error';
        }
    }

    function showSmaError(message) {
        elements.smaError.innerHTML = `
            <div class="status-message error">
                <span class="status-icon">✗</span>
                <span>${message}</span>
            </div>
        `;
    }

    function clearSmaError() {
        elements.smaError.innerHTML = '';
    }

    // Chart Rendering
    function renderChart(data) {
        if (state.chart) {
            state.chart.destroy();
        }

        const ctx = elements.chartContainer.getContext('2d');
        const isRaw = state.currentAggregation === 'raw';
        const unit = isRaw ? 'W' : 'kWh';
        const isLineChart = isRaw;

        const datasets = [];

        // Main data (import / consumption)
        datasets.push({
            label: isRaw ? 'Power' : 'Import',
            type: isLineChart ? 'line' : 'bar',
            data: data.data,
            backgroundColor: 'rgba(0, 212, 170, 0.6)',
            borderColor: '#00d4aa',
            borderWidth: 2,
            ...(isLineChart && {
                pointRadius: 0,
                pointHoverRadius: 4,
                tension: 0.4
            }),
            fill: false,
            order: 1
        });

        // Export data (for aggregated views)
        if (!isRaw && data.export_data) {
            datasets.push({
                label: 'Export',
                type: 'bar',
                data: data.export_data,
                backgroundColor: 'rgba(255, 193, 7, 0.6)',
                borderColor: '#ffc107',
                borderWidth: 2,
                order: 2
            });
        }

        // Forecast
        if (data.forecast && !isRaw && state.currentAggregation !== 'daily') {
            datasets.push({
                label: 'Forecast',
                type: 'line',
                data: data.forecast,
                backgroundColor: 'rgba(255, 193, 7, 0.2)',
                borderColor: '#ffc107',
                borderWidth: 2,
                borderDash: [8, 4],
                pointRadius: 3,
                pointHoverRadius: 5,
                pointBackgroundColor: '#ffc107',
                pointBorderColor: '#ffc107',
                tension: 0.4,
                fill: true,
                order: 3
            });
        }

        // Moving average
        const averageNames = {
            daily: '90-Day Average',
            weekly: '5-Week Average',
            monthly: '5-Month Average',
            yearly: '3-Year Average'
        };

        if (data.moving_average && averageNames[state.currentAggregation]) {
            datasets.push({
                label: averageNames[state.currentAggregation],
                type: 'line',
                data: data.moving_average,
                borderColor: '#ff6b6b',
                borderWidth: 2,
                pointRadius: 0,
                pointHoverRadius: 4,
                tension: 0.4,
                fill: false,
                order: 0
            });
        }

        // Daily average pattern for raw view
        if (isRaw && data.daily_average_pattern) {
            datasets.push({
                label: 'Average Pattern',
                type: 'line',
                data: data.daily_average_pattern,
                borderColor: '#ffa500',
                borderWidth: 2,
                pointRadius: 0,
                pointHoverRadius: 4,
                tension: 0.4,
                fill: false,
                order: 4
            });
        }

        state.chart = new Chart(ctx, {
            data: {
                labels: data.labels,
                datasets: datasets
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'index',
                    intersect: false
                },
                plugins: {
                    legend: {
                        position: 'top',
                        labels: {
                            color: '#94a3b8',
                            font: {
                                size: 12
                            },
                            padding: 16,
                            usePointStyle: true
                        }
                    },
                    tooltip: {
                        backgroundColor: 'rgba(0, 0, 0, 0.9)',
                        borderColor: '#00d4aa',
                        borderWidth: 1,
                        titleColor: '#fff',
                        titleFont: {
                            size: 13,
                            weight: 600
                        },
                        bodyColor: '#fff',
                        bodyFont: {
                            size: 13
                        },
                        padding: 12,
                        displayColors: true,
                        callbacks: {
                            label: function(context) {
                                let label = context.dataset.label || '';
                                if (label) {
                                    label += ': ';
                                }
                                if (context.parsed.y !== null) {
                                    label += context.parsed.y.toFixed(2) + ' ' + unit;
                                }
                                return label;
                            }
                        }
                    },
                    zoom: {
                        zoom: {
                            wheel: {
                                enabled: true,
                                speed: 0.1
                            },
                            drag: {
                                enabled: true,
                                backgroundColor: 'rgba(0, 212, 170, 0.2)',
                                borderColor: '#00d4aa',
                                borderWidth: 1
                            },
                            mode: 'x'
                        },
                        pan: {
                            enabled: true,
                            mode: 'x'
                        },
                        limits: {
                            x: {min: 'original', max: 'original'}
                        }
                    }
                },
                scales: {
                    x: {
                        ticks: {
                            color: '#94a3b8',
                            font: {
                                size: 11
                            },
                            maxRotation: data.labels.length > 50 ? 45 : 0,
                            autoSkip: true,
                            autoSkipPadding: 10
                        },
                        grid: {
                            color: 'rgba(255, 255, 255, 0.05)',
                            drawBorder: false
                        }
                    },
                    y: {
                        title: {
                            display: true,
                            text: unit,
                            color: '#94a3b8',
                            font: {
                                size: 12
                            }
                        },
                        ticks: {
                            color: '#94a3b8',
                            font: {
                                size: 11
                            },
                            callback: function(value) {
                                return value.toFixed(1);
                            }
                        },
                        grid: {
                            color: 'rgba(255, 255, 255, 0.05)',
                            drawBorder: false
                        }
                    }
                }
            }
        });
    }

    // Update Chart Data
    async function updateChart() {
        try {
            let url = `/api/chart-data?aggregation=${state.currentAggregation}`;

            if (state.currentAggregation === 'raw') {
                const selectedDate = state.flatpickrInstance?.selectedDates[0];
                if (selectedDate) {
                    const year = selectedDate.getFullYear();
                    const month = String(selectedDate.getMonth() + 1).padStart(2, '0');
                    const day = String(selectedDate.getDate()).padStart(2, '0');
                    const dateStr = `${year}-${month}-${day}`;
                    url += `&day=${dateStr}`;
                } else {
                    renderChart({ labels: [], data: [] });
                    return;
                }
            }

            const chartData = await fetchData(url);
            renderChart(chartData);
        } catch (error) {
            console.error('Error loading chart:', error);
            showSmaError('Error loading chart data');
        }
    }

    // Aggregation Change
    function handleAggregationChange(event) {
        state.currentAggregation = event.target.value;

        if (state.currentAggregation === 'raw') {
            elements.datePickerContainer.classList.remove('hidden');
        } else {
            elements.datePickerContainer.classList.add('hidden');
        }

        updateChart();
    }

    // Initialize
    async function initialize() {
        try {
            // Get latest date for default
            let defaultDate = 'today';
            try {
                const data = await fetchData('/api/latest-date');
                if (data.latest_date) defaultDate = data.latest_date;
            } catch {
                // Use today as default date
            }

            // Initialize Flatpickr
            state.flatpickrInstance = flatpickr(elements.datePickerInput, {
                dateFormat: "Y-m-d",
                defaultDate: defaultDate,
                theme: "dark",
                maxDate: "today",
                onChange: () => {
                    if (state.currentAggregation === 'raw') updateChart();
                }
            });

            // Event listeners
            elements.aggregationControls.forEach(radio =>
                radio.addEventListener('change', handleAggregationChange)
            );

            // Window resize
            window.addEventListener('resize', () => {
                if (state.chart) state.chart.resize();
            });

            // Load initial data
            await updateChart();
            await updateStats();
            await updateSmaStatus();

            // Poll status periodically
            setInterval(updateSmaStatus, 30000);
            setInterval(updateStats, 30000);
            // Live-refresh the chart so new readings appear without a page reload
            setInterval(updateChart, 5000);
        } catch (error) {
            console.error('Initialization error:', error);
            showSmaError('Initialization error. Please refresh the page.');
        }
    }

    initialize();
});
