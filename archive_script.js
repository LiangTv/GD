// archive_script.js

// 簡易繁簡轉換字典 (與 index.html 中的保持一致或從共享檔案引入)
const tsMap = {'剧':'劇','集':'集','电':'電','影':'影','杂':'雜','志':'誌','时':'時','间':'間','档':'檔','案':'案','更':'更','新':'新','列':'列','表':'表','签':'簽','标':'標','题':'題','内':'內','容':'容','搜':'搜','寻':'尋','显':'顯','示':'示','隐':'隱','藏':'藏','数':'數','据':'據','库': '庫','简':'簡','繁':'繁','体':'體','字':'字','转':'轉','换':'換','优':'優','化':'化','验':'驗','证':'證','权':'權','限':'限','设':'設','置':'置','错':'錯','误':'誤','讯':'訊','息':'息','系':'系','统':'統','环':'環','境':'境','版':'版','本':'本','处':'處','理':'理','回':'回','应': '應','网':'網','页':'頁','浏':'瀏','览':'覽','器':'器','缓':'緩','存':'存','清':'清','除':'除','模':'模','块':'塊','组':'組','织':'織','结':'結','构':'構','状':'狀','态':'態','负':'負','载':'載','压':'壓','力':'力','测':'測','试':'試','性':'性','能':'能','调':'調','优':'優','部':'部', '署':'署','迭':'疊','代':'代','开':'開','发':'發','周':'週','期':'期','计':'計','划':'劃','实':'實','现':'現','功':'功','能':'能','需':'需','求':'求','规':'規','范':'範','说':'說','明':'明','书':'書','用':'用','户':'戶','体':'體','验':'驗','界':'界','面':'面','计':'計','交互':'互動', '动':'動','画':'畫','视':'視','觉':'覺','元':'元','素':'素','图':'圖','标':'標','颜':'顏','色':'色','体':'體','排':'排','版':'版','布':'佈','局':'局','响':'響','应':'應','式':'式','适':'適','配':'配','不':'不','同':'同','备':'備','屏':'屏','幕':'幕','尺':'尺','寸':'寸','全':'全','漫':'漫', ' ': ' '};
const stMap = {}; for (const t in tsMap) { stMap[tsMap[t]] = t; }
function toSimp(t) { if(!t) return ""; let r=""; for(let i=0;i<t.length;i++) { r += stMap[t[i]]||t[i]; } return r; }
function toTrad(t) { if(!t) return ""; let r=""; for(let i=0;i<t.length;i++) { r += tsMap[t[i]]||t[i]; } return r; }

function escapeHTML(str) {
    if (!str) return "";
    return str.replace(/&/g, '&amp;')
              .replace(/</g, '&lt;')
              .replace(/>/g, '&gt;')
              .replace(/"/g, '&quot;')
              .replace(/'/g, '&#039;');
}


document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('archive-search-input');
    const resultsContainer = document.getElementById('archive-results-container'); // 用於放置 Tab 和內容
    const tabButtonsContainer = document.getElementById('archive-tab-buttons');
    const tabContentContainer = document.getElementById('archive-tab-content');
    const loadingIndicator = document.getElementById('loading-indicator');
    const paginationControls = document.getElementById('archive-pagination-controls');
    const prevPageBtn = document.getElementById('prev-page');
    const nextPageBtn = document.getElementById('next-page');
    const pageInfoSpan = document.getElementById('page-info');
    const itemsPerPageSelect = document.getElementById('items-per-page-select');
    const gotoPageInput = document.getElementById('goto-page-input');
    const gotoPageBtn = document.getElementById('goto-page-btn');


    let allData = []; // 儲存從 JSON 載入的全部資料
    let filteredData = []; // 儲存過濾後的資料
    let currentPage = 1;
    let itemsPerPage = parseInt(itemsPerPageSelect.value, 10);
    let currentActiveCategory = 'tvshow'; // 預設分類，可以從 URL 參數獲取或固定

    const categoriesOrder = [
        { key: 'tvshow', title: '劇集' },
        { key: 'movie', title: '電影' },
        { key: 'collection', title: '全集' },
        { key: 'animation', title: '動漫' },
        { key: 'magazine', title: '雜誌' },
        { key: 'unknown', title: '未分類' }
    ];

    itemsPerPageSelect.addEventListener('change', function() {
        itemsPerPage = parseInt(this.value, 10);
        currentPage = 1; // 重設到第一頁
        renderCurrentPage();
        updatePaginationControls();
    });

    gotoPageBtn.addEventListener('click', function() {
        const pageNum = parseInt(gotoPageInput.value, 10);
        const totalPages = Math.ceil(filteredData.length / itemsPerPage);
        if (pageNum >= 1 && pageNum <= totalPages) {
            currentPage = pageNum;
            renderCurrentPage();
            updatePaginationControls();
        } else {
            alert(`請輸入介於 1 和 ${totalPages} 之間的頁碼。`);
        }
    });


    function fetchData() {
        loadingIndicator.style.display = 'block';
        paginationControls.style.display = 'none';
        // JSON 檔案應該與 archive.html 在同一目錄層級或相對路徑正確
        fetch('media_updates.json')
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                allData = data.map(item => {
                    // 確保 timestamp 是 Date 物件，方便後續處理
                    item.timestamp_obj = new Date(item.timestamp); // 假設 timestamp 是 ISO 格式
                    return item;
                });
                // 預設按時間倒序 (JSON 本身應該已經是，以防萬一)
                allData.sort((a, b) => b.timestamp_obj - a.timestamp_obj);
                
                generateTabButtons(); // 根據載入的資料動態生成 Tab
                // 模擬點擊預設的 active tab (如果有的話)
                const activeTabButton = tabButtonsContainer.querySelector('.tab-button.active');
                if (activeTabButton) {
                    currentActiveCategory = activeTabButton.getAttribute('data-category');
                } else if (tabButtonsContainer.firstChild) { // 如果沒有 active，選第一個
                    currentActiveCategory = tabButtonsContainer.firstChild.getAttribute('data-category');
                    tabButtonsContainer.firstChild.classList.add('active');
                }
                
                applyFilterAndRender();
                loadingIndicator.style.display = 'none';
            })
            .catch(error => {
                console.error('Error fetching or parsing media_updates.json:', error);
                resultsContainer.innerHTML = '<p class="no-results">載入歷史記錄失敗，請稍後再試。</p>';
                loadingIndicator.style.display = 'none';
            });
    }

    function generateTabButtons() {
        tabButtonsContainer.innerHTML = ''; // 清空現有按鈕
        let categoriesWithData = new Set();
        allData.forEach(item => categoriesWithData.add(item.category));

        // 確保預設分類按鈕最先被考慮
        let defaultCatInfo = categoriesOrder.find(c => c.key === DEFAULT_CATEGORY);
        let firstAvailableCategoryKey = null;

        if (defaultCatInfo && categoriesWithData.has(defaultCatInfo.key)) {
            createTabButton(defaultCatInfo.key, defaultCatInfo.title, true);
            firstAvailableCategoryKey = defaultCatInfo.key;
        }

        categoriesOrder.forEach(cat => {
            if (cat.key !== DEFAULT_CATEGORY && categoriesWithData.has(cat.key)) {
                createTabButton(cat.key, cat.title, false);
                if (!firstAvailableCategoryKey) {
                    firstAvailableCategoryKey = cat.key;
                }
            }
        });

        // 如果經過排序後，預設的 activeCategory 仍然沒有按鈕，則選擇第一個可用的
        if (!tabButtonsContainer.querySelector(`.tab-button[data-category="${currentActiveCategory}"]`) && firstAvailableCategoryKey) {
            currentActiveCategory = firstAvailableCategoryKey;
            const firstButton = tabButtonsContainer.querySelector(`.tab-button[data-category="${firstAvailableCategoryKey}"]`);
            if (firstButton) firstButton.classList.add('active');
        }

        // Tab 按鈕事件綁定
        tabButtonsContainer.addEventListener('click', function(event) {
            if (event.target.classList.contains('tab-button')) {
                const targetCategory = event.target.getAttribute('data-category');
                tabButtonsContainer.querySelectorAll('.tab-button').forEach(button => button.classList.remove('active'));
                event.target.classList.add('active');
                currentActiveCategory = targetCategory;
                currentPage = 1; // 切換 Tab 時重置到第一頁
                applyFilterAndRender();
            }
        });
    }
    
    function createTabButton(categoryKey, categoryTitle, isActive = false) {
        const button = document.createElement('button');
        button.className = 'tab-button';
        button.setAttribute('data-category', categoryKey);
        button.textContent = categoryTitle;
        if (isActive) {
            button.classList.add('active');
            currentActiveCategory = categoryKey; // 設定當前活動分類
        }
        tabButtonsContainer.appendChild(button);
    }


    function applyFilterAndRender() {
        const searchTerm = searchInput.value.toLowerCase().trim();
        
        if (searchTerm === "") {
            // 無搜尋詞：顯示當前 active category 的所有資料
            filteredData = allData.filter(item => item.category === currentActiveCategory);
        } else {
            const searchTrad = toTrad(searchTerm);
            const searchSimp = toSimp(searchTerm);

            filteredData = allData.filter(item => {
                if (item.category !== currentActiveCategory) return false; // 只搜尋當前 Tab

                const filename = (item.filename || "").toLowerCase();
                const path = (item.relative_path || "").toLowerCase();
                let textToSearch = (item.category === 'magazine') ? filename : path;
                
                const targetTrad = toTrad(textToSearch);
                const targetSimp = toSimp(textToSearch);

                return (targetTrad.includes(searchTrad) || targetTrad.includes(searchSimp)) ||
                       (targetSimp.includes(searchTrad) || targetSimp.includes(searchSimp));
            });
        }
        currentPage = 1; // 每次搜尋或切換 Tab 都回到第一頁
        renderCurrentPage();
        updatePaginationControls();
    }

    function renderCurrentPage() {
        tabContentContainer.innerHTML = ''; // 清空舊的內容面板

        const paneId = `pane-${currentActiveCategory}`;
        let currentPane = document.getElementById(paneId);
        if (!currentPane) {
            currentPane = document.createElement('div');
            currentPane.className = 'content-pane active'; // 直接設為 active
            currentPane.id = paneId;
            tabContentContainer.appendChild(currentPane);
        } else {
            currentPane.innerHTML = ''; // 清空面板內容以便重新渲染
            currentPane.classList.add('active'); 
        }

        const start = (currentPage - 1) * itemsPerPage;
        const end = start + itemsPerPage;
        const paginatedItems = filteredData.slice(start, end);

        if (paginatedItems.length === 0) {
            currentPane.innerHTML = '<p class="no-results">此條件下無符合的記錄。</p>';
            return;
        }

        // 按月、日分組並渲染 (類似 Python 中的邏輯)
        const monthGroups = {};
        paginatedItems.forEach(item => {
            // 確保 timestamp_obj 是 Date 物件
            if (!(item.timestamp_obj instanceof Date) || isNaN(item.timestamp_obj)) {
                item.timestamp_obj = new Date(item.timestamp); // 再次嘗試轉換
                 if (isNaN(item.timestamp_obj)) item.timestamp_obj = new Date(0); // 極端情況給個預設
            }

            const yearMonth = `${item.timestamp_obj.getFullYear()}-${(item.timestamp_obj.getMonth() + 1).toString().padStart(2, '0')}`;
            if (!monthGroups[yearMonth]) {
                monthGroups[yearMonth] = {};
            }
            const day = `${yearMonth}-${item.timestamp_obj.getDate().toString().padStart(2, '0')}`;
            if (!monthGroups[yearMonth][day]) {
                monthGroups[yearMonth][day] = [];
            }
            monthGroups[yearMonth][day].push(item);
        });

        // 獲取最新日期 (在當前分頁的資料中)
        let latestDateInPage = null;
        if (paginatedItems.length > 0) {
            latestDateInPage = paginatedItems.reduce((max, p) => p.timestamp_obj > max ? p.timestamp_obj : max, paginatedItems[0].timestamp_obj).setHours(0,0,0,0);
        }


        for (const yearMonth of Object.keys(monthGroups).sort().reverse()) {
            const monthDate = new Date(yearMonth + "-01");
            const monthH3 = document.createElement('h3');
            monthH3.textContent = `${monthDate.getFullYear()} 年 ${(monthDate.getMonth() + 1)} 月`;
            currentPane.appendChild(monthH3);

            for (const day of Object.keys(monthGroups[yearMonth]).sort().reverse()) {
                const dayItems = monthGroups[yearMonth][day];
                const dayDate = new Date(day);
                const dayH4 = document.createElement('h4');
                dayH4.className = 'day-header';
                dayH4.innerHTML = `<span class="toggle-icon">+</span> ${dayDate.toLocaleDateString('zh-TW', { month: '2-digit', day: '2-digit', weekday: 'long' })}`;
                
                const listUl = document.createElement('ul');
                listUl.className = 'update-list';
                const listId = `archive-list-${currentActiveCategory}-${day.replace(/-/g, '')}`;
                listUl.id = listId;
                dayH4.setAttribute('data-target', `#${listId}`);

                const dayGroupDiv = document.createElement('div');
                dayGroupDiv.className = 'day-group';
                
                // 判斷是否預設展開 (最新一天)
                if (latestDateInPage && dayDate.setHours(0,0,0,0) === latestDateInPage) {
                    dayGroupDiv.classList.add('expanded');
                    listUl.classList.add('visible');
                    dayH4.querySelector('.toggle-icon').textContent = '-';
                }


                dayItems.forEach(item => {
                    const li = document.createElement('li');
                    li.className = 'update-item';
                    // 為搜尋準備 data-* 屬性
                    li.setAttribute('data-filename', escapeHTML(item.category === 'magazine' ? item.filename : ''));
                    li.setAttribute('data-path', escapeHTML(item.relative_path));
                    li.setAttribute('data-category', escapeHTML(item.category));

                    let itemHTML = `
                        <div class="item-header">
                            <strong>${escapeHTML(item.filename)}</strong>
                            <span class="item-time">${item.timestamp_obj.toLocaleTimeString('zh-TW', {hour12: false})}</span>
                        </div>
                        <div class="file-path">${escapeHTML(item.relative_path)}</div>
                    `;
                    if (item.tmdb_url) {
                        itemHTML += `<a href="${item.tmdb_url}" target="_blank" class="tmdb-link">TMDb 連結</a>`;
                    }
                    if (item.plot) {
                        itemHTML += `<blockquote>${escapeHTML(item.plot)}</blockquote>`;
                    }
                    li.innerHTML = itemHTML;
                    listUl.appendChild(li);
                });
                dayGroupDiv.appendChild(dayH4);
                dayGroupDiv.appendChild(listUl);
                currentPane.appendChild(dayGroupDiv);
            }
        }
    }

    function updatePaginationControls() {
        const totalItems = filteredData.length;
        const totalPages = Math.ceil(totalItems / itemsPerPage);

        if (totalPages <= 1) {
            paginationControls.style.display = 'none';
            return;
        }
        paginationControls.style.display = 'block';
        pageInfoSpan.textContent = `第 ${currentPage} / ${totalPages} 頁 (共 ${totalItems} 項)`;
        prevPageBtn.disabled = currentPage === 1;
        nextPageBtn.disabled = currentPage === totalPages;
        gotoPageInput.max = totalPages;
        gotoPageInput.value = currentPage;
    }

    // 事件綁定
    if (searchInput) {
        searchInput.addEventListener('input', () => {
            currentPage = 1; // 搜尋時重置到第一頁
            applyFilterAndRender();
        });
    }
    if(prevPageBtn) {
        prevPageBtn.addEventListener('click', () => {
            if (currentPage > 1) {
                currentPage--;
                renderCurrentPage();
                updatePaginationControls();
            }
        });
    }
    if(nextPageBtn) {
        nextPageBtn.addEventListener('click', () => {
            const totalPages = Math.ceil(filteredData.length / itemsPerPage);
            if (currentPage < totalPages) {
                currentPage++;
                renderCurrentPage();
                updatePaginationControls();
            }
        });
    }

    // 初始載入
    fetchData();
});