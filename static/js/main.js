document.addEventListener('DOMContentLoaded', () => {
    // Search containers
    const searchWrapper = document.getElementById('searchWrapper');
    const carSearchContainer = document.getElementById('carSearchContainer');
    const regionSearchContainer = document.getElementById('regionSearchContainer');

    // Input elements
    const searchInput = document.getElementById('searchInput');
    const searchBtn = document.getElementById('searchBtn');
    const suggestionsList = document.getElementById('suggestionsList');
    
    const regionSelect = document.getElementById('regionSelect');
    const searchRegionBtn = document.getElementById('searchRegionBtn');
    
    // UI states
    const spinner = document.getElementById('spinner');
    const dashboardContent = document.getElementById('dashboardContent');
    const infoState = document.getElementById('infoState');
    const mainTitle = document.getElementById('mainTitle');
    
    // Layout grids
    const carResultsGrid = document.getElementById('carResultsGrid');
    const regionResultsGrid = document.getElementById('regionResultsGrid');
    
    // KPI Elements
    const kpiQuantity = document.getElementById('kpiQuantity');
    const kpiValue = document.getElementById('kpiValue');
    const kpiTransactions = document.getElementById('kpiTransactions');
    
    const kpiDeptTitle = document.getElementById('kpiDeptTitle');
    const kpiDept = document.getElementById('kpiDept');
    
    // Table Bodies (Car Mode)
    const detailedTableBody = document.getElementById('detailedTableBody');
    const descTableBody = document.getElementById('descTableBody');
    
    // Table Bodies (Region Mode)
    const regionDetailedTableBody = document.getElementById('regionDetailedTableBody');
    const regionVehiclesTableBody = document.getElementById('regionVehiclesTableBody');
    
    // State variables
    let allTransactions = [];
    let uniquePlates = []; // Array of { original, normalized }
    let uniqueRegions = [];
    let debounceTimer;
    let currentMode = 'car'; // 'car' or 'region'
    let activePrintData = null;
    
    // Sort and search state cache
    let currentCarTransactions = [];
    let currentRegionTransactions = [];
    let sortState = {
        table: null,
        key: null,
        direction: 'desc'
    };

    // Normalize Arabic strings
    function normalizeArabic(text) {
        if (!text) return "";
        let val = text.trim();
        const arabicMatch = val.match(/[\u0600-\u06FF]/);
        if (arabicMatch) {
            const idx = arabicMatch.index;
            const before = val.substring(0, idx);
            let after = val.substring(idx);
            after = after.replace(/0/g, ' ');
            val = before + after;
        }
        val = val.replace(/[أإآ]/g, 'ا')
                 .replace(/ة/g, 'ه')
                 .replace(/ى/g, 'ي');
        val = val.replace(/\s+/g, ' ');
        return val.toLowerCase().trim();
    }

    // Format numbers
    const formatNumber = (num, decimals = 2) => {
        return new Intl.NumberFormat('en-US', {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals
        }).format(num);
    };

    // Product badge classes
    const getProductClass = (product) => {
        if (!product) return 'tag-product';
        if (product.includes('92')) return 'tag-product benzin-92';
        if (product.includes('95')) return 'tag-product benzin-95';
        if (product.includes('سولار') || product.includes('ديزل')) return 'tag-product solar';
        return 'tag-product';
    };

    // Sort transactions array
    const sortTransactions = (txsArray, key, direction) => {
        txsArray.sort((a, b) => {
            let valA = a[key];
            let valB = b[key];
            
            if (key === 'quantity' || key === 'value') {
                valA = parseFloat(valA) || 0;
                valB = parseFloat(valB) || 0;
                if (valA < valB) return direction === 'asc' ? -1 : 1;
                if (valA > valB) return direction === 'asc' ? 1 : -1;
                return 0;
            } else if (key === 'movement_number') {
                valA = parseInt(valA) || 0;
                valB = parseInt(valB) || 0;
                if (valA < valB) return direction === 'asc' ? -1 : 1;
                if (valA > valB) return direction === 'asc' ? 1 : -1;
                return 0;
            } else if (key === 'plate') {
                const cmp = String(valA).localeCompare(String(valB), 'ar', { numeric: true });
                if (cmp !== 0) {
                    return direction === 'asc' ? cmp : -cmp;
                }
                const dateA = a.date || "";
                const dateB = b.date || "";
                return dateA.localeCompare(dateB);
            } else {
                const cmp = String(valA).localeCompare(String(valB), 'ar');
                if (cmp !== 0) {
                    return direction === 'asc' ? cmp : -cmp;
                }
                return 0;
            }
        });
    };

    // Update the sort icons in the headers
    const updateHeaderIcons = (tableType) => {
        document.querySelectorAll(`.sortable-header[data-table="${tableType}"]`).forEach(th => {
            const icon = th.querySelector('i');
            const key = th.getAttribute('data-key');
            if (sortState.table === tableType && sortState.key === key) {
                if (sortState.direction === 'asc') {
                    icon.className = 'fas fa-sort-up';
                    icon.style.opacity = '1';
                    icon.style.color = 'var(--accent-color)';
                } else {
                    icon.className = 'fas fa-sort-down';
                    icon.style.opacity = '1';
                    icon.style.color = 'var(--accent-color)';
                }
            } else {
                icon.className = 'fas fa-sort';
                icon.style.opacity = '0.5';
                icon.style.color = '';
            }
        });
    };

    // Helper to generate odometer cell HTML
    const getOdometerCellHTML = (tx) => {
        const userDept = localStorage.getItem('user_department');
        const isEditable = (userDept === 'admin') || (userDept && userDept !== 'general' && tx.department === userDept);
        
        const odoVal = tx.odometer || "";
        
        // Rule: If odometer is already recorded, it cannot be modified (read-only)
        if (odoVal) {
            return `<span class="text-number text-bold" style="color: #10b981;">${odoVal}</span>`; // green text
        }
        
        if (isEditable) {
            return `
                <div class="odo-edit-container">
                    <input type="text" class="odo-input text-number" value="${odoVal}" placeholder="العداد..." data-movement="${tx.movement_number}">
                    <button class="odo-save-btn" onclick="saveOdometer('${tx.movement_number}', this)" title="حفظ"><i class="fas fa-save"></i></button>
                </div>
            `;
        } else {
            return `<span class="text-number">-</span>`;
        }
    };

    // Save odometer handler
    window.saveOdometer = (movementNumber, buttonEl) => {
        const container = buttonEl.closest('.odo-edit-container');
        const inputEl = container.querySelector('.odo-input');
        const newOdometer = inputEl.value.trim();
        
        if (!newOdometer) {
            alert('يرجى إدخال قراءة العداد أولاً.');
            return;
        }
        
        inputEl.disabled = true;
        buttonEl.disabled = true;
        const originalHTML = buttonEl.innerHTML;
        buttonEl.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
        
        const userDept = localStorage.getItem('user_department');
        
        fetch('/api/transaction/odometer', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                movement_number: movementNumber,
                odometer: newOdometer,
                department: userDept
            })
        })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                // Update cached state
                const txCar = currentCarTransactions.find(t => t.movement_number === movementNumber);
                if (txCar) txCar.odometer = newOdometer;
                
                const txRegion = currentRegionTransactions.find(t => t.movement_number === movementNumber);
                if (txRegion) txRegion.odometer = newOdometer;
                
                // Re-render to enforce the read-only rule immediately
                const isCarMode = (document.getElementById('carResultsGrid').style.display === 'grid');
                if (isCarMode) {
                    renderCarDetailedTable(currentCarTransactions);
                } else {
                    renderRegionDetailedTable(currentRegionTransactions);
                }
            } else {
                inputEl.disabled = false;
                buttonEl.disabled = false;
                buttonEl.innerHTML = originalHTML;
                alert(data.error || 'حدث خطأ أثناء حفظ قراءة العداد.');
                inputEl.style.borderColor = '#ef4444';
            }
        })
        .catch(err => {
            inputEl.disabled = false;
            buttonEl.disabled = false;
            buttonEl.innerHTML = originalHTML;
            console.error(err);
            alert('حدث خطأ في الاتصال بالخادم لحفظ قراءة العداد.');
            inputEl.style.borderColor = '#ef4444';
        });
    };

    // Render Car Detailed Table
    const renderCarDetailedTable = (txs) => {
        detailedTableBody.innerHTML = '';
        txs.forEach(tx => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${getOdometerCellHTML(tx)}</td>
                <td class="text-number text-bold">${tx.movement_number}</td>
                <td class="text-number">${tx.date}</td>
                <td class="text-number text-bold">${formatNumber(tx.quantity, 2)}</td>
                <td class="text-number text-bold">${formatNumber(tx.value, 2)}</td>
                <td>${tx.station}</td>
                <td class="text-bold">${tx.description}</td>
            `;
            detailedTableBody.appendChild(tr);
        });
        updateHeaderIcons('car');
    };

    // Render Region Detailed Table
    const renderRegionDetailedTable = (txs) => {
        regionDetailedTableBody.innerHTML = '';
        txs.forEach(tx => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${getOdometerCellHTML(tx)}</td>
                <td class="text-number text-bold">${tx.movement_number}</td>
                <td class="text-number">${tx.date}</td>
                <td class="text-bold">${tx.plate}</td>
                <td class="text-number text-bold">${formatNumber(tx.quantity, 2)}</td>
                <td class="text-number text-bold">${formatNumber(tx.value, 2)}</td>
                <td>${tx.station}</td>
                <td class="text-bold">${tx.description}</td>
            `;
            regionDetailedTableBody.appendChild(tr);
        });
        updateHeaderIcons('region');
    };

    // Add click listeners to headers
    document.querySelectorAll('.sortable-header').forEach(header => {
        header.addEventListener('click', () => {
            const table = header.getAttribute('data-table');
            const key = header.getAttribute('data-key');
            
            let dir = 'desc';
            if (sortState.table === table && sortState.key === key) {
                dir = sortState.direction === 'desc' ? 'asc' : 'desc';
            }
            
            sortState.table = table;
            sortState.key = key;
            sortState.direction = dir;
            
            if (table === 'car') {
                sortTransactions(currentCarTransactions, key, dir);
                renderCarDetailedTable(currentCarTransactions);
            } else if (table === 'region') {
                sortTransactions(currentRegionTransactions, key, dir);
                renderRegionDetailedTable(currentRegionTransactions);
            }
        });
    });

    // Helper to find most frequent item in array
    function getMostFrequent(arr) {
        if (arr.length === 0) return 'غير محدد';
        const modeMap = {};
        let maxEl = arr[0], maxCount = 1;
        for (let i = 0; i < arr.length; i++) {
            const el = arr[i];
            if (!el || el === 'nan' || el === 'غير محدد') continue;
            if (modeMap[el] == null) modeMap[el] = 1;
            else modeMap[el]++;
            if (modeMap[el] > maxCount) {
                maxEl = el;
                maxCount = modeMap[el];
            }
        }
        return maxEl;
    }

    // Load static data on startup
    const loadStaticData = () => {
        spinner.style.display = 'block';
        infoState.style.display = 'none';

        // Fetch departments to populate region select
        fetch('/api/departments')
            .then(res => {
                if (!res.ok) {
                    throw new Error('تعذر تحميل قائمة الإدارات.');
                }
                return res.json();
            })
            .then(departments => {
                uniqueRegions = departments;
                
                // Populate Region Select options
                regionSelect.innerHTML = '<option value="">اختر المنطقة / إدارة التشغيل...</option>';
                uniqueRegions.forEach(reg => {
                    const opt = document.createElement('option');
                    opt.value = reg;
                    opt.innerText = reg;
                    regionSelect.appendChild(opt);
                });

                spinner.style.display = 'none';
                
                const userDept = localStorage.getItem('user_department');
                // Startup routing depending on role
                if (userDept && userDept !== 'admin' && userDept !== 'general') {
                    // Department Mode: Hide region select completely, show car search full width
                    regionSearchContainer.style.display = 'none';
                    carSearchContainer.style.display = 'flex';
                    currentMode = 'region';
                    
                    // Render department stats immediately
                    performRegionSearch(userDept);
                } else {
                    // Admin Mode: Show both controls side-by-side
                    searchWrapper.classList.add('admin-layout');
                    carSearchContainer.style.display = 'flex';
                    regionSearchContainer.style.display = 'flex';
                    
                    resetDashboard();
                }
            })
            .catch(err => {
                spinner.style.display = 'none';
                infoState.innerHTML = `
                    <div class="info-icon"><i class="fas fa-exclamation-triangle"></i></div>
                    <h3>حدث خطأ أثناء تحميل البيانات</h3>
                    <p>يرجى التأكد من اتصال خادم Flask وقاعدة بيانات MongoDB بنجاح.</p>
                `;
                infoState.classList.add('error');
                infoState.style.display = 'block';
                console.error(err);
            });
    };
    loadStaticData();

    // Helper to revert dashboard to general report when search is cleared
    const revertToGeneralReport = () => {
        suggestionsList.style.display = 'none';
        const userDept = localStorage.getItem('user_department');
        if (userDept && userDept !== 'admin' && userDept !== 'general') {
            currentMode = 'region';
            performRegionSearch(userDept);
        } else {
            const selectedRegion = regionSelect.value;
            if (selectedRegion) {
                currentMode = 'region';
                performRegionSearch(selectedRegion);
            } else {
                resetDashboard();
            }
        }
    };

    const resetDashboard = () => {
        dashboardContent.classList.remove('active');
        infoState.style.display = 'block';
        infoState.classList.remove('error');
        
        const userDept = localStorage.getItem('user_department');
        const isDept = userDept && userDept !== 'admin' && userDept !== 'general';
        
        if (isDept) {
            if (mainTitle) mainTitle.innerText = `منظومة الاستعلام عن حركات صرف المركبات - ${userDept}`;
            infoState.innerHTML = `
                <div class="info-icon"><i class="fas fa-search-dollar"></i></div>
                <h3>بانتظار البحث...</h3>
                <p>يرجى إدخال رقم لوحة السيارة للبحث عنها داخل إدارتكم.</p>
            `;
        } else {
            if (mainTitle) mainTitle.innerText = 'منظومة الاستعلام عن حركات صرف المركبات';
            infoState.innerHTML = `
                <div class="info-icon"><i class="fas fa-map-marked-alt"></i></div>
                <h3>بانتظار اختيار المنطقة أو الاستعلام عن سيارة...</h3>
                <p>يرجى اختيار منطقة من تصفية الإدارات لعرض تقرير المنطقة، أو كتابة رقم لوحة السيارة للاستعلام التفصيلي.</p>
            `;
        }
    };

    // Autocomplete Input Listener (Car Mode)
    searchInput.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        const query = searchInput.value.trim();
        
        if (!query) {
            suggestionsList.style.display = 'none';
            revertToGeneralReport();
            return;
        }

        debounceTimer = setTimeout(() => {
            const userDept = localStorage.getItem('user_department');
            let url = `/api/search/autocomplete?q=${encodeURIComponent(query)}`;
            if (userDept && userDept !== 'admin' && userDept !== 'general') {
                url += `&department=${encodeURIComponent(userDept)}`;
            }
            fetch(url)
                .then(res => res.json())
                .then(matches => {
                    renderSuggestions(matches);
                })
                .catch(err => {
                    console.error("Autocomplete fetch error:", err);
                });
        }, 150);
    });

    const renderSuggestions = (suggestions) => {
        suggestionsList.innerHTML = '';
        if (suggestions.length === 0) {
            suggestionsList.style.display = 'none';
            return;
        }

        suggestions.forEach(item => {
            const li = document.createElement('li');
            li.innerHTML = `<i class="fas fa-car-side"></i><span>${item}</span>`;
            li.addEventListener('click', () => {
                searchInput.value = item;
                suggestionsList.style.display = 'none';
                performCarSearch(item);
            });
            suggestionsList.appendChild(li);
        });
        suggestionsList.style.display = 'block';
    };

    // Close suggestions list clicking outside
    document.addEventListener('click', (e) => {
        if (e.target !== searchInput && e.target !== suggestionsList) {
            suggestionsList.style.display = 'none';
        }
    });

    // Handle Search triggers (Car Mode)
    searchInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            const val = searchInput.value.trim();
            if (val) {
                suggestionsList.style.display = 'none';
                performCarSearch(val);
            } else {
                revertToGeneralReport();
            }
        }
    });

    searchBtn.addEventListener('click', () => {
        const val = searchInput.value.trim();
        if (val) {
            suggestionsList.style.display = 'none';
            performCarSearch(val);
        } else {
            revertToGeneralReport();
        }
    });

    // Handle HTML5 native clear button (x) inside search boxes
    searchInput.addEventListener('search', () => {
        if (!searchInput.value.trim()) {
            revertToGeneralReport();
        }
    });

    // Handle Region Search triggers
    searchRegionBtn.addEventListener('click', () => {
        const reg = regionSelect.value;
        if (reg) {
            searchInput.value = '';
            performRegionSearch(reg);
        }
    });

    regionSelect.addEventListener('change', () => {
        const reg = regionSelect.value;
        if (reg) {
            searchInput.value = '';
            performRegionSearch(reg);
        } else {
            resetDashboard();
        }
    });

    // Perform Car Search against backend API
    const performCarSearch = (plate) => {
        spinner.style.display = 'block';
        dashboardContent.classList.remove('active');
        infoState.style.display = 'none';

        const userDept = localStorage.getItem('user_department');
        let url = `/api/search/car?plate=${encodeURIComponent(plate)}`;
        if (userDept && userDept !== 'admin' && userDept !== 'general') {
            url += `&department=${encodeURIComponent(userDept)}`;
        }
        fetch(url)
            .then(res => {
                if (!res.ok) {
                    return res.json().then(errData => {
                        throw new Error(errData.error || 'لم نجد نتائج للسيارة المطلوبة');
                    });
                }
                return res.json();
            })
            .then(data => {
                const txs = data.transactions;
                const totalQuantity = data.total_quantity;
                const totalValue = data.total_value;
                const dominantDept = data.dominant_department;
                const descriptionTotals = data.description_totals;

                // Configure KPI Headers for Car Mode
                kpiDeptTitle.innerText = 'الإدارة التشغيلية الغالبة';

                // Update main title
                if (mainTitle) {
                    const isDeptUser = userDept && userDept !== 'admin' && userDept !== 'general';
                    const activeDept = isDeptUser ? userDept : dominantDept;
                    mainTitle.innerText = `منظومة الاستعلام عن حركات صرف المركبات - ${activeDept}`;
                }

                // Populate KPIs
                kpiQuantity.innerHTML = `${formatNumber(totalQuantity, 2)} <span class="kpi-unit">لتر</span>`;
                kpiValue.innerHTML = `${formatNumber(totalValue, 2)} <span class="kpi-unit">ج.م</span>`;
                kpiTransactions.innerHTML = `${txs.length} <span class="kpi-unit">حركة</span>`;
                kpiDept.innerText = dominantDept;

                // Cache transactions and render using sorting
                currentCarTransactions = txs;
                sortState.table = 'car';
                sortState.key = 'date';
                sortState.direction = 'asc';
                renderCarDetailedTable(currentCarTransactions);

                // Populate description table
                descTableBody.innerHTML = '';
                descriptionTotals.forEach(item => {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `
                        <td class="text-bold">${item.description}</td>
                        <td class="text-number text-bold">${formatNumber(item.quantity, 2)}</td>
                        <td class="text-number text-bold">${formatNumber(item.value, 2)}</td>
                    `;
                    descTableBody.appendChild(tr);
                });

                // Toggle Results Panels
                carResultsGrid.style.display = 'grid';
                regionResultsGrid.style.display = 'none';

                // Save print data
                activePrintData = {
                    mode: 'car',
                    query: plate,
                    data: descriptionTotals,
                    total_quantity: totalQuantity,
                    total_value: totalValue,
                    transactions: txs
                };

                spinner.style.display = 'none';
                dashboardContent.classList.add('active');
            })
            .catch(err => {
                spinner.style.display = 'none';
                infoState.innerHTML = `
                    <div class="info-icon"><i class="fas fa-exclamation-triangle"></i></div>
                    <h3>لم نجد نتائج</h3>
                    <p>${err.message || 'لم يتم العثور على أي حركة صرف لرقم السيارة المدخل.'}</p>
                `;
                infoState.classList.add('error');
                infoState.style.display = 'block';
                console.error(err);
            });
    };

    // Perform Region Search against backend API
    const performRegionSearch = (regionName) => {
        spinner.style.display = 'block';
        dashboardContent.classList.remove('active');
        infoState.style.display = 'none';

        fetch(`/api/search/region?region=${encodeURIComponent(regionName)}`)
            .then(res => {
                if (!res.ok) {
                    return res.json().then(errData => {
                        throw new Error(errData.error || 'لم نجد نتائج للمنطقة المطلوبة');
                    });
                }
                return res.json();
            })
            .then(data => {
                const txs = data.transactions;
                const totalQuantity = data.total_quantity;
                const totalValue = data.total_value;
                const vehiclesCount = data.vehicles_count;
                const vehiclesList = data.vehicles_list;

                // Configure KPI Headers for Region Mode
                kpiDeptTitle.innerText = 'عدد السيارات بالمنطقة';

                // Update main title
                if (mainTitle) {
                    mainTitle.innerText = `منظومة الاستعلام عن حركات صرف المركبات - ${regionName}`;
                }

                // Populate KPIs
                kpiQuantity.innerHTML = `${formatNumber(totalQuantity, 2)} <span class="kpi-unit">لتر</span>`;
                kpiValue.innerHTML = `${formatNumber(totalValue, 2)} <span class="kpi-unit">ج.م</span>`;
                kpiTransactions.innerHTML = `${txs.length} <span class="kpi-unit">حركة</span>`;
                kpiDept.innerHTML = `${vehiclesCount} <span class="kpi-unit">سيارة</span>`;

                // Cache transactions and render using sorting
                currentRegionTransactions = txs;
                sortState.table = 'region';
                sortState.key = 'plate';
                sortState.direction = 'asc';
                
                // Sort by plate (ascending, naturally) and then by date (ascending)
                currentRegionTransactions.sort((a, b) => {
                    const plateA = a.plate || "";
                    const plateB = b.plate || "";
                    if (plateA !== plateB) {
                        return plateA.localeCompare(plateB, 'ar', { numeric: true });
                    }
                    const dateA = a.date || "";
                    const dateB = b.date || "";
                    return dateA.localeCompare(dateB);
                });
                
                renderRegionDetailedTable(currentRegionTransactions);

                // Populate Region Vehicles Table
                regionVehiclesTableBody.innerHTML = '';
                vehiclesList.forEach(veh => {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `
                        <td class="text-bold">${veh.description}</td>
                        <td class="text-number text-bold">${formatNumber(veh.quantity, 2)}</td>
                        <td class="text-number text-bold">${formatNumber(veh.value, 2)}</td>
                        <td class="text-number">${veh.transactions}</td>
                    `;
                    regionVehiclesTableBody.appendChild(tr);
                });

                // Toggle Results Panels
                regionResultsGrid.style.display = 'grid';
                carResultsGrid.style.display = 'none';

                // Save print data
                activePrintData = {
                    mode: 'region',
                    query: regionName,
                    data: vehiclesList,
                    total_quantity: totalQuantity,
                    total_value: totalValue,
                    transactions: txs
                };

                spinner.style.display = 'none';
                dashboardContent.classList.add('active');
            })
            .catch(err => {
                spinner.style.display = 'none';
                infoState.innerHTML = `
                    <div class="info-icon"><i class="fas fa-exclamation-triangle"></i></div>
                    <h3>لم نجد نتائج</h3>
                    <p>${err.message || 'لم يتم العثور على أي حركات صرف لهذه المنطقة.'}</p>
                `;
                infoState.classList.add('error');
                infoState.style.display = 'block';
                console.error(err);
            });
    };

    // Helper to get month text from transactions
    function getMonthText(transactions) {
        if (!transactions || transactions.length === 0) return "";
        const monthsArabic = {
            "01": "يناير", "02": "فبراير", "03": "مارس", "04": "أبريل",
            "05": "مايو", "06": "يونيو", "07": "يوليو", "08": "أغسطس",
            "09": "سبتمبر", "10": "أكتوبر", "11": "نوفمبر", "12": "ديسمبر"
        };
        const uniqueMonths = new Set();
        const uniqueYears = new Set();
        transactions.forEach(tx => {
            if (tx.date) {
                const match = tx.date.match(/^(\d{4})-(\d{2})-/);
                if (match) {
                    uniqueYears.add(match[1]);
                    uniqueMonths.add(match[2]);
                }
            }
        });
        const yearText = uniqueYears.size > 0 ? Array.from(uniqueYears).sort().join(' - ') : "";
        if (uniqueMonths.size === 0) return "";
        const sortedMonths = Array.from(uniqueMonths).sort();
        const monthNames = sortedMonths.map(m => monthsArabic[m] || m);
        return monthNames.length === 1 ? `شهر ${monthNames[0]} ${yearText}` : `الأشْهُر: ${monthNames.join('، ')} ${yearText}`;
    }

    // Helper to generate summary table HTML
    function getSummaryTableHtml(mode, data, total_quantity, total_value) {
        const isRegion = (mode === 'region');
        const header = isRegion 
            ? `<tr><th>نوع الوقود المنصرف</th><th>إجمالي الكمية (لتر)</th><th>إجمالي القيمة (ج.م)</th><th>عدد الحركات</th></tr>`
            : `<tr><th>نوع الوقود المنصرف</th><th>إجمالي الكمية (لتر)</th><th>إجمالي القيمة (ج.م)</th></tr>`;
        
        let totalTxs = 0;
        const rows = data.map(item => {
            if (isRegion) totalTxs += parseInt(item.transactions) || 0;
            return `<tr>
                <td class="print-text-bold">${item.description}</td>
                <td class="print-text-number">${formatNumber(item.quantity, 2)}</td>
                <td class="print-text-number">${formatNumber(item.value, 2)}</td>
                ${isRegion ? `<td class="print-text-number">${item.transactions}</td>` : ''}
            </tr>`;
        }).join('');

        const totalRow = isRegion
            ? `<tr class="print-total-row"><td>الإجمالي العام</td><td class="print-text-number print-text-bold">${formatNumber(total_quantity, 2)}</td><td class="print-text-number print-text-bold">${formatNumber(total_value, 2)}</td><td class="print-text-number print-text-bold">${totalTxs}</td></tr>`
            : `<tr class="print-total-row"><td>الإجمالي العام</td><td class="print-text-number print-text-bold">${formatNumber(total_quantity, 2)}</td><td class="print-text-number print-text-bold">${formatNumber(total_value, 2)}</td></tr>`;
        
        return `<table><thead>${header}</thead><tbody>${rows}${totalRow}</tbody></table>`;
    }

    // Helper to sort print transactions
    function sortPrintTransactions(mode, txs) {
        const isRegion = (mode === 'region');
        return [...txs].sort((a, b) => {
            const keyA = isRegion ? (a.plate || "") : (a.description || "");
            const keyB = isRegion ? (b.plate || "") : (b.description || "");
            if (keyA !== keyB) {
                return isRegion 
                    ? keyA.localeCompare(keyB, 'ar', { numeric: true }) 
                    : keyA.localeCompare(keyB, 'ar');
            }
            return (a.date || "").localeCompare(b.date || "");
        });
    }

    // Helper to generate detailed transactions table HTML
    function getDetailedTableHtml(mode, transactions) {
        if (!transactions || transactions.length === 0) return "";
        const isRegion = (mode === 'region');
        const sorted = sortPrintTransactions(mode, transactions);
        const headers = `<tr><th>م</th><th>قراءة العداد</th><th>رقم الحركة</th><th>تاريخ حركة الصرف</th>${isRegion ? '<th>رقم السيارة</th>' : ''}<th>كمية الصرف (لتر)</th><th>قيمة الصرف (ج.م)</th><th>اسم المحطة</th><th>نوع الوقود المنصرف</th></tr>`;
        
        const rows = sorted.map((tx, idx) => `<tr>
            <td class="print-text-number" style="text-align: center;">${idx + 1}</td>
            <td class="print-text-number" style="text-align: center;">${tx.odometer || '-'}</td>
            <td class="print-text-number print-text-bold" style="text-align: center;">${tx.movement_number}</td>
            <td class="print-text-number" style="text-align: center;">${tx.date || ''}</td>
            ${isRegion ? `<td class="print-text-bold" style="text-align: center;">${tx.plate || ''}</td>` : ''}
            <td class="print-text-number print-text-bold">${formatNumber(tx.quantity, 2)}</td>
            <td class="print-text-number print-text-bold">${formatNumber(tx.value, 2)}</td>
            <td>${tx.station || ''}</td>
            <td class="print-text-bold">${tx.description || ''}</td>
        </tr>`).join('');

        return `<table class="print-details-table"><thead>${headers}</thead><tbody>${rows}</tbody></table>`;
    }

    // Helper to compile the entire report markup
    function generateReportMarkup(report) {
        const { mode, query, data, total_quantity, total_value, transactions } = report;
        const monthText = getMonthText(transactions || []);
        const docTitle = mode === 'region' ? `قيمة و كمية الوقود المستهلك علي السيارات - ${query}` : `قيمة و كمية الوقود المستهلك علي السيارة - ${query}`;
        const tableTitle = mode === 'region' ? 'اجمالي استهلاك السيارات بالمنطقة' : 'تفاصيل استهلاك السيارة من الوقود';
        const summaryTable = getSummaryTableHtml(mode, data, total_quantity, total_value);
        const detailedTable = getDetailedTableHtml(mode, transactions);
        const metaHtml = monthText ? `<p class="print-doc-meta">${monthText}</p>` : '';

        let html = `<div class="print-report-container print-page-chunk">
            <div class="print-doc-header"><h1 class="print-doc-title">${docTitle}</h1>${metaHtml}</div>
            <div class="print-table-wrapper"><h2 class="print-table-title">${tableTitle}</h2>${summaryTable}</div>
            <div class="print-signature-section"><span>مسؤول التشغيل: ........................</span><span>يعتمد: ........................</span></div>
        </div>`;

        if (transactions && transactions.length > 0) {
            const detailsTitle = `سجل تفاصيل الحركة - ${mode === 'region' ? 'ادارة' : 'سيارة'} ${query} ${monthText ? `- ${monthText}` : ''}`;
            html += `<div class="print-report-container print-page-chunk" style="margin-top: 2rem;">
                <div class="print-doc-header" style="margin-bottom: 1.5rem;"><h2 class="print-doc-title" style="font-size: 1.3rem;">${detailsTitle}</h2></div>
                <div class="print-table-wrapper">${detailedTable}</div>
            </div>`;
        }
        return html;
    }

    // Handle Print Button
    const printReportBtn = document.getElementById('printReportBtn');
    if (printReportBtn) {
        printReportBtn.addEventListener('click', () => {
            if (!activePrintData) {
                alert('لا توجد بيانات للطباعة حالياً.');
                return;
            }
            const printArea = document.getElementById('printArea');
            if (printArea) {
                printArea.innerHTML = generateReportMarkup(activePrintData);
                window.print();
                printArea.innerHTML = '';
            }
        });
    }
});

