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
            } else if (key === 'movement_number') {
                valA = parseInt(valA) || 0;
                valB = parseInt(valB) || 0;
            } else {
                valA = String(valA).toLowerCase();
                valB = String(valB).toLowerCase();
            }
            
            if (valA < valB) return direction === 'asc' ? -1 : 1;
            if (valA > valB) return direction === 'asc' ? 1 : -1;
            return 0;
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

    // Render Car Detailed Table
    const renderCarDetailedTable = (txs) => {
        detailedTableBody.innerHTML = '';
        txs.forEach(tx => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
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
                sortState.direction = 'desc';
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
                sortState.key = 'date';
                sortState.direction = 'desc';
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
});
