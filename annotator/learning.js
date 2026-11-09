// Searchable reference. Reading and the local trainer never modify a project.
window.Learning = ({storageKey}) => {
  const $ = id => document.getElementById(id);
  const make = (tag, text = '', className = '') => {
    const element = document.createElement(tag); element.textContent = text; element.className = className; return element;
  };
  const articles = [
  {
    "id": "start",
    "title": "От схемы к результату",
    "group": "Начало работы",
    "intro": "Архитектор работает на вашем компьютере без регистрации.",
    "sections": [
      {
        "title": "От схемы к результату",
        "paragraphs": [
          "Создайте пустую схему, откройте каталог кнопкой + и добавьте блоки. Соедините выходы и входы совместимых типов.",
          "Сохранить записывает схему на локальный диск и резервную копию в браузере. Запустить сохраняет связанную схему и выполняет её; результаты доступны в Запусках и Результатах."
        ]
      }
    ]
  },
  {
    "id": "projects",
    "title": "Сохранение и проекты",
    "group": "Начало работы",
    "intro": "Проект — редактируемая схема, запуск — запись одного её выполнения.",
    "sections": [
      {
        "title": "Сохранение и проекты",
        "paragraphs": [
          "Проекты доступны через + → Каталог проектов. История запусков сохраняется отдельно.",
          "При запуске через Docker данные лежат в папке data рядом с compose.yaml. Сделайте резервную копию всей папки после остановки приложения. Экспорт JSON позволяет обменяться схемой; датасеты и секреты нужно переносить отдельно."
        ]
      }
    ]
  },
  {
    "id": "blocks",
    "title": "Блоки и связи",
    "group": "Блоки и связи",
    "intro": "В каталоге есть Библиотека стандартных блоков и Мои блоки.",
    "sections": [
      {
        "title": "Блоки и связи",
        "paragraphs": [
          "В Моих блоках сохраняются созданные вами блоки этого рабочего пространства. Поиск фильтрует названия и категории.",
          "Перетащите соединение от выхода одного блока ко входу другого. Подписи портов показывают, какие данные ожидаются."
        ]
      }
    ]
  },
  {
    "id": "data",
    "title": "CSV и датасеты",
    "group": "Данные",
    "intro": "Добавьте свой CSV или настройте собственное подключение Kaggle.",
    "sections": [
      {
        "title": "CSV и датасеты",
        "paragraphs": [
          "Кнопка Просмотреть данные позволяет проверить кодировку, разделитель и колонки. Авто подходит для UTF-8 и BOM; для других файлов выберите исходную кодировку и проверьте читаемость текста.",
          "Файлы и результаты остаются на этом компьютере. Kaggle и Hugging Face требуют сети для загрузки; локальные сохранённые данные доступны без неё."
        ]
      }
    ]
  },
  {
    "id": "python",
    "title": "Python-блок",
    "group": "Блоки и связи",
    "intro": "Python-блок обрабатывает входы и возвращает результаты через функцию run(inputs, params).",
    "sections": [
      {
        "title": "Python-блок",
        "paragraphs": [
          "Код выполняется в Docker без сети и доступа к файлам ноутбука. Доступны NumPy, pandas и scikit-learn. Настройки CPU и памяти задаются при запуске локальной среды.",
          "Пробный запуск помогает проверить код и журнал ошибок. Для передачи таблицы используйте порт rows, для отчёта — report."
        ]
      }
    ]
  },
  {
    "id": "runs",
    "title": "Запуски и результаты",
    "group": "Запуски и результаты",
    "intro": "Запустить выполняет цепочку на ресурсах вашего компьютера.",
    "sections": [
      {
        "title": "Запуски и результаты",
        "paragraphs": [
          "В Запусках можно открыть сохранённую схему конкретного выполнения, проверить шаги и журналы. Сохранение схемы само по себе ничего не обучает.",
          "При ошибке откройте журнал проблемного блока. Во время работы следующая задача может ждать в очереди."
        ]
      }
    ]
  },
  {
    "id": "models",
    "title": "Модели и обучение",
    "group": "Запуски и результаты",
    "intro": "CPU-модели выполняются локально. GPU требует совместимого устройства и отдельной установки PyTorch.",
    "sections": [
      {
        "title": "Модели и обучение",
        "paragraphs": [
          "Отделяйте тренировочную, валидационную и тестовую выборки. Препроцессинг обучайте на тренировочных данных, чтобы не допустить утечки.",
          "Лимиты памяти, размера промежуточного JSON и времени остаются. Пакетное обучение зависит от выбранного алгоритма; сам перенос на ноутбук не снимает ограничения данных."
        ]
      }
    ]
  },
  {
    "id": "chat",
    "title": "AI Chat и своя модель",
    "group": "AI и подключения",
    "intro": "При первом открытии AI Chat выберите способ подключения.",
    "sections": [
      {
        "title": "AI Chat и своя модель",
        "paragraphs": [
          "Codex использует ваш аккаунт. Другая модель подключается через совместимый API: адрес с /v1, название модели и необязательный API-ключ. Для модели на хосте при запуске в Docker используйте host.docker.internal.",
          "Проверить API запрашивает список моделей. Поддержка редактирования схем требует вызова инструментов. AI предлагает изменения, а вы просматриваете и применяете их.",
          "При отправке сообщения включённый контекст передаёт схему, журналы и доступные фрагменты данных выбранному провайдеру. Не подключайте облачную модель для данных, которые не хотите передавать наружу."
        ]
      }
    ]
  },
  {
    "id": "mcp",
    "title": "Внешний AI через MCP",
    "group": "AI и подключения",
    "intro": "MCP позволяет вашему AI-клиенту читать и редактировать локальные схемы.",
    "sections": [
      {
        "title": "Внешний AI через MCP",
        "paragraphs": [
          "Откройте AI Chat → Настроить AI → Подключить внешний AI через MCP. Скопируйте локальный адрес и выберите Streamable HTTP в клиенте.",
          "Общение происходит во внешнем клиенте. MCP не подключает произвольную модель к встроенному чату автоматически. Не открывайте локальный порт в интернет."
        ]
      }
    ]
  },
  {
    "id": "design-docs",
    "title": "Дизайн-документы",
    "group": "Начало работы",
    "intro": "Документ состоит из пяти разделов: проблема, таргет, данные и признаки, метрика и проверка, модель и обучение.",
    "sections": [
      {
        "title": "Дизайн-документы",
        "paragraphs": [
          "Создайте документ, заполните разделы и сохраните. Экспорт JSON и Импорт JSON позволяют обмениваться документами без каталога сообщества.",
          "Добавить в AI Chat прикрепляет версию документа. Прочитать открывает её, Обновить получает новые правки, Убрать удаляет только вложение. Прикрепление само по себе не отправляет сообщение и не строит схему."
        ]
      }
    ]
  },
  {
    "id": "chat-files",
    "title": "Файлы в AI Chat",
    "group": "AI и подключения",
    "intro": "Через скрепку можно приложить документы к сообщению.",
    "sections": [
      {
        "title": "Файлы в AI Chat",
        "paragraphs": [
          "Модель читает поддерживаемое текстовое содержимое по запросу. Изображения и сканированные PDF не гарантируют распознавание без OCR.",
          "Лимиты файла и количества вложений показаны при добавлении. Документ отправляется только вашему настроенному AI."
        ]
      }
    ]
  },
  {
    "id": "board",
    "title": "Доска",
    "group": "Начало работы",
    "intro": "Доска сохраняется локально и предназначена для самостоятельной работы.",
    "sections": [
      {
        "title": "Доска",
        "paragraphs": [
          "Добавляйте заметки, фигуры и стрелки. Результат можно скачать в PDF. Совместный доступ по ссылке в этой версии отсутствует."
        ]
      }
    ]
  },
  {
    "id": "help",
    "title": "Если что-то не работает",
    "group": "Решение проблем",
    "intro": "Проверьте журнал шага и доступные ресурсы компьютера.",
    "sections": [
      {
        "title": "Если что-то не работает",
        "paragraphs": [
          "Для Python-блока должен работать Docker и контейнер runner. Для загрузок нужна сеть; локальная работа с CSV не требует ключей.",
          "Если модель AI не отвечает, проверьте адрес API, название модели и ключ. Для CPU-обучения установите requirements-ml.txt. Сохраняйте важные данные перед обновлением приложения."
        ]
      }
    ]
  }
];

  const groups = ['Начало работы', 'Данные', 'Блоки и связи', 'Запуски и результаты', 'AI и подключения', 'Совместная работа', 'Практика', 'Решение проблем'];
  articles.sort((a, b) => groups.indexOf(a.group) - groups.indexOf(b.group));
  const legacyOrder = ['start', 'blocks', 'ports', 'practice', 'data', 'models', 'runs', 'projects', 'subgraphs', 'community', 'help'];
  let index = 0;
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || 'null');
    const found = articles.findIndex(article => article.id === (saved?.lessonId || legacyOrder[saved?.index]));
    if (found >= 0) index = found;
  } catch { /* Reading works without local storage. */ }
  const persist = () => { try { localStorage.setItem(storageKey, JSON.stringify({lessonId: articles[index].id})); } catch {} };
  const dialog = make('dialog'); dialog.id = 'learning-dialog'; dialog.setAttribute('aria-labelledby', 'learn-title');
  const heading = make('header', '', 'learn-heading');
  const title = make('h2', 'Справочник Архитектора'); title.id = 'learn-title';
  const close = make('button', '×'); close.id = 'learn-close'; close.type = 'button'; close.setAttribute('aria-label', 'Закрыть справочник'); close.onclick = () => dialog.close();
  heading.append(title, close);
  const layout = make('div', '', 'learn-layout');
  const sidebar = make('details', '', 'learn-sidebar'); sidebar.id = 'learn-topics';
  sidebar.append(make('summary', 'Темы и поиск'));
  const searchLabel = make('label', 'Поиск по справочнику'); searchLabel.htmlFor = 'learn-search';
  const searchBox = make('div', '', 'learn-search-box');
  const search = make('input'); search.type = 'search'; search.id = 'learn-search'; search.placeholder = 'Например, сохранить'; search.autocomplete = 'off';
  const clear = make('button', '×'); clear.type = 'button'; clear.id = 'learn-search-clear'; clear.hidden = true; clear.setAttribute('aria-label', 'Очистить поиск');
  searchBox.append(search, clear);
  const searchStatus = make('p', '', 'learn-search-status'); searchStatus.setAttribute('role', 'status'); searchStatus.id = 'learn-search-status';
  const nav = make('nav'); nav.id = 'learn-nav'; nav.setAttribute('aria-label', 'Темы справочника');
  sidebar.append(searchLabel, searchBox, searchStatus, nav);
  const main = make('article', '', 'learn-main'); main.id = 'learn-content'; main.tabIndex = 0; main.setAttribute('aria-label', 'Статья справочника');
  const toc = make('details', '', 'learn-toc'); toc.id = 'learn-toc'; toc.append(make('summary', 'На этой странице'));
  const tocNav = make('nav'); tocNav.setAttribute('aria-label', 'На этой странице'); toc.append(tocNav);
  layout.append(sidebar, toc, main); dialog.append(heading, layout); document.body.append(dialog);
  const narrow = matchMedia('(max-width:760px)');
  const setLayout = () => { sidebar.open = !narrow.matches; toc.open = !narrow.matches; toc.firstChild.tabIndex = narrow.matches ? 0 : -1; };
  toc.firstChild.onclick = event => { if (!narrow.matches) event.preventDefault(); };
  setLayout(); narrow.addEventListener('change', setLayout);
  const intro = null;
  if (intro) {
    const quick = make('button', 'Быстрый старт на телефоне'); quick.id = 'learn-mobile-intro'; quick.type = 'button';
    quick.onclick = () => { dialog.close(); intro.open(true); }; sidebar.append(quick);
  }
  let returnFocus = null;
  function open() { returnFocus = document.activeElement; render(); if (!dialog.open) dialog.showModal(); close.focus(); }
  dialog.addEventListener('close', () => { $('learning').classList.remove('nav-active'); const target = returnFocus?.getClientRects().length ? returnFocus : $('mobile-menu'); target?.focus({preventScroll: true}); });
  for (const id of ['learning', 'welcome-learning']) { $(id).onclick = open; $(id).disabled = false; }
  const searchable = article => [article.title, article.intro, ...article.sections.flatMap(section => [section.title, ...section.paragraphs, ...(section.steps || []), section.code || ''])].join(' ');
  function navigate(position) {
    index = position; persist(); render();
    if (narrow.matches) { sidebar.open = false; toc.open = false; }
    main.scrollTop = 0; dialog.scrollTop = 0;
    $('learn-lesson-title').focus({preventScroll: true});
  }
  function renderNav() {
    nav.replaceChildren();
    const query = search.value.trim().toLocaleLowerCase('ru'); clear.hidden = !search.value;
    let group = '', found = 0;
    articles.forEach((article, position) => {
      const text = searchable(article), at = text.toLocaleLowerCase('ru').indexOf(query);
      if (query && at < 0) return;
      ++found;
      if (!query && group !== article.group) { group = article.group; nav.append(make('h3', group, 'learn-nav-group')); }
      const button = make('button'); button.type = 'button'; button.dataset.lesson = article.id;
      if (position === index) button.setAttribute('aria-current', 'page');
      button.append(make('span', article.title));
      if (query) {
        const start = Math.max(0, at - 28), end = Math.min(text.length, at + query.length + 65);
        const excerpt = make('small');
        if (start) excerpt.append('…');
        excerpt.append(text.slice(start, at), make('mark', text.slice(at, at + query.length)), text.slice(at + query.length, end));
        if (end < text.length) excerpt.append('…'); button.append(excerpt);
      }
      button.onclick = () => navigate(position); nav.append(button);
    });
    searchStatus.textContent = query ? (found ? `Найдено тем: ${found}` : 'Ничего не найдено. Попробуйте другое слово.') : '';
    searchStatus.hidden = !query;
  }
  search.oninput = renderNav;
  clear.onclick = () => { search.value = ''; renderNav(); search.focus(); };
  search.onkeydown = event => { if (event.key === 'Enter') { event.preventDefault(); nav.querySelector('button')?.click(); } };
  function render() {
    renderNav(); main.replaceChildren(); tocNav.replaceChildren();
    const article = articles[index];
    main.append(make('p', article.group, 'learn-meta'));
    const title = make('h1', article.title); title.id = 'learn-lesson-title'; title.tabIndex = -1;
    main.append(title, make('p', article.intro, 'learn-lead'));
    article.sections.forEach((section, position) => {
      const element = make('section', '', 'learn-section');
      const sectionTitle = make('h2', section.title); sectionTitle.id = `learn-${article.id}-${position}`; sectionTitle.tabIndex = -1;
      const link = make('a', section.title); link.href = '#' + sectionTitle.id;
      link.onclick = event => { event.preventDefault(); if (narrow.matches) toc.open = false; sectionTitle.scrollIntoView({block: 'start'}); sectionTitle.focus({preventScroll: true}); };
      tocNav.append(link); element.append(sectionTitle);
      for (const paragraph of section.paragraphs) element.append(make('p', paragraph));
      if (section.steps) { const steps = make('ol'); for (const step of section.steps) steps.append(make('li', step)); element.append(steps); }
      if (section.code) { const pre = make('pre', '', 'learn-code'); pre.append(make('code', section.code)); element.append(pre); }
      if (article.id === 'practice' && position === 1) element.append(renderPractice());
      main.append(element);
    });
    const footer = make('footer', '', 'learn-footer');
    if (index > 0) { const previous = make('button', '← ' + articles[index - 1].title); previous.type = 'button'; previous.onclick = () => navigate(index - 1); footer.append(previous); }
    if (index < articles.length - 1) { const next = make('button', articles[index + 1].title + ' →'); next.type = 'button'; next.onclick = () => navigate(index + 1); footer.append(next); }
    else { const back = make('button', 'Вернуться в редактор'); back.type = 'button'; back.onclick = () => dialog.close(); footer.append(back); }
    main.append(footer); main.scrollTop = 0;
  }
  const practice = {selected: '', connected: false, factor: '2'};
  function renderPractice() {
    const box = make('div', '', 'learn-practice'); box.setAttribute('aria-label', 'Тренажёр передачи данных');
    const flow = make('div', '', 'learn-flow'), source = make('div', '', 'learn-flow-card'), target = make('div', '', 'learn-flow-card');
    source.append(make('strong', 'Чтение CSV')); target.append(make('strong', 'Обработка строк'));
    const arrow = make('span', '→', 'learn-arrow'); arrow.setAttribute('aria-hidden', 'true');
    const status = make('p', '', 'learn-feedback'); status.id = 'learn-connection'; status.setAttribute('role', 'status');
    const result = make('pre', 'Здесь появится результат.', 'learn-result'); result.id = 'learn-result'; result.setAttribute('role', 'status');
    const run = make('button', 'Показать результат', 'primary'); run.type = 'button'; run.id = 'learn-run'; run.disabled = !practice.connected;
    const reset = () => { result.textContent = 'Здесь появится результат.'; run.disabled = !practice.connected; arrow.dataset.connected = String(practice.connected); };
    for (const [type, label] of [['row', 'Выход: Строка'], ['rows', 'Выход: Строки']]) {
      const port = make('button', label); port.type = 'button'; port.dataset.port = type; port.setAttribute('aria-pressed', String(practice.selected === type));
      port.onclick = () => { practice.selected = type; practice.connected = false; for (const other of source.querySelectorAll('button')) other.setAttribute('aria-pressed', String(other === port)); status.textContent = 'Теперь нажмите вход «Строки» справа.'; delete status.dataset.success; reset(); };
      source.append(port);
    }
    const input = make('button', 'Вход: Строки'); input.type = 'button';
    input.onclick = () => { practice.connected = practice.selected === 'rows'; status.dataset.success = String(practice.connected); status.textContent = practice.connected ? 'Связь готова: строки → строки.' : 'Типы не совпадают. Выберите выход «Строки».'; reset(); };
    target.append(input); flow.append(source, arrow, target);
    const label = make('label', 'Коэффициент умножения'), factor = make('input'); factor.id = 'learn-factor'; factor.type = 'number'; factor.min = '-100'; factor.max = '100'; factor.step = 'any'; factor.value = practice.factor; label.append(factor);
    factor.oninput = () => { practice.factor = factor.value; reset(); };
    run.onclick = () => {
      if (!practice.connected) return;
      if (!factor.value || !factor.checkValidity()) { result.textContent = 'Введите коэффициент от −100 до 100.'; factor.focus(); return; }
      const rows = [{value: 3}, {value: 7}].map(row => ({...row, double: row.value * Number(factor.value)}));
      result.textContent = JSON.stringify({rows}, null, 2);
    };
    if (practice.connected) status.textContent = 'Связь готова: строки → строки.';
    arrow.dataset.connected = String(practice.connected);
    box.append(flow, status, label, run, result); return box;
  }
  return {startMobileIntro: () => intro?.autoOpen()};
};

// Short phone introduction. Slides never execute blocks or change a project.