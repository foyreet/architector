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
          "Если вы пока выясняете, какую задачу решать и как оценить результат, откройте в справочнике группу «Проектирование ML». Там показан путь от вопросов к кейсам, метрикам и дизайн-документу.",
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
          "Данные лежат в папке data рядом с приложением. Сделайте резервную копию всей папки после остановки приложения. Экспорт JSON позволяет обменяться схемой; датасеты и секреты нужно переносить отдельно."
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
          "Код выполняется отдельным процессом с правами вашего пользователя: ему доступны сеть и файлы компьютера. Доступны NumPy, pandas и scikit-learn. Блок работает до завершения или остановки. При необходимости лимит памяти задаётся переменной ARCHITECTOR_PYTHON_MEMORY_MB.",
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
          "Блоки передают данные целиком. Объём задачи зависит от памяти компьютера и выбранного алгоритма."
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
          "Codex использует ваш аккаунт. Другая модель подключается через совместимый API: адрес с /v1, название модели и необязательный API-ключ. Для модели на этом компьютере используйте её адрес localhost.",
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
    "id": "problem-space",
    "title": "Пространство проблем",
    "group": "Проектирование ML",
    "intro": "Начните с решения, которое предстоит принять. Например, команда рассылок хочет понять, кому отправить письмо, какое выбрать и когда лучше пропустить отправку.",
    "sections": [
      {
        "title": "От задачи к трём уровням вопросов",
        "paragraphs": [],
        "steps": [
          "Откройте «Пространство проблем» в меню. Нажмите корень дерева и запишите задачу команды своими словами.",
          "Нажмите «Добавить общий вопрос». Например, «Как команда сейчас выбирает получателей?» Запишите ответ в карточке.",
          "Выберите этот вопрос и нажмите «Добавить уточнение». Спросите, какие клиенты участвуют в выборе. В карточке уточнения нажмите «Добавить технический вопрос» и спросите, какое поле позволяет определить этих клиентов до отправки."
        ]
      },
      {
        "title": "Как углубить ветвь с AI",
        "paragraphs": [
          "Для предложений подключите модель в AI Chat. На пустом дереве откройте «Предложить вопросы с AI», опишите задачу и нажмите «Запросить вопросы». Для уточнения конкретного ответа выберите его карточку и нажмите «Углубить с AI». Модель получает формулировку, вопросы с ответами, ваш запрос и выбранную ветвь.",
          "Проверьте, какое решение зависит от ответа на каждый вопрос. Например, знание о цене лишнего письма поможет выбрать ограничение на частоту рассылки. Нажмите «Добавить в дерево» и заполните ответы сами."
        ]
      },
      {
        "title": "Как передать ответы в пространство решений",
        "paragraphs": [
          "Дайте дереву название и нажмите «Сохранить». Кнопка «Пространство решений →» откроет кейсы для этого дерева. Для разбивки на кейсы нужен хотя бы один заполненный ответ.",
          "В «Мои деревья» можно открыть другую задачу, создать новое дерево или перенести дерево вопросов через JSON."
        ]
      }
    ]
  },
  {
    "id": "solution-space",
    "title": "Пространство решений",
    "group": "Проектирование ML",
    "intro": "Здесь ответы команды превращаются в кейсы. Для рассылок это могут быть две разные задачи — выбрать действие для клиента и оценить результат выбранного правила.",
    "sections": [
      {
        "title": "Как получить кейсы из ответов",
        "paragraphs": [],
        "steps": [
          "Перейдите из дерева вопросов или выберите сохранённое дерево в «Пространстве решений». Раскройте «Ответы из дерева» и проверьте, что нужные ответы попали в контекст.",
          "Нажмите «Разбить на кейсы с AI». В каждом предложении проверьте критерий готовности, возможный подход, предположения и компромиссы. Раскройте «На каких ответах основан кейс».",
          "Нажмите «Принять кейсы», отредактируйте формулировки и нажмите «Сохранить кейсы». Если принять новую подборку взамен прежней, она заменит и кейсы, и связанные с ними подборки источников."
        ]
      },
      {
        "title": "Как найти успехи и неудачи",
        "paragraphs": [
          "В принятом кейсе отредактируйте два поисковых запроса. Для бизнесового сходства опишите решение команды и желаемый эффект, например выбор рассылки по приросту выручки. Для технического сходства укажите метод и условия, например оценку эффекта письма по рандомизированному эксперименту.",
          "Нажмите «Найти аналоги в интернете». Эти запросы используются для поиска разборов внедрений и неудач, публикаций в arXiv и Crossref, репозиториев на GitHub. В карточке источника оценки бизнесового и технического сходства показаны отдельно."
        ]
      },
      {
        "title": "Что взять в дизайн-документ",
        "paragraphs": [
          "Откройте первоисточник и проверьте, какой результат наблюдала команда и какие условия совпадают с вашими. Если исход не установлен, зафиксируйте, что ещё нужно проверить. Нажмите «Сохранить кейсы» после поиска. В черновик документа можно включить выбранные кейсы с их источниками."
        ]
      }
    ]
  },
  {
    "id": "metric-tree",
    "title": "Иерархия метрик",
    "group": "Проектирование ML",
    "intro": "Постройте дерево от бизнес-цели до показателей, которые сможете измерить. Ветви могут иметь разную глубину. Дерево метрик можно подготовить отдельно от вопросов и кейсов.",
    "sections": [
      {
        "title": "От бизнес-цели к измерению",
        "paragraphs": [],
        "steps": [
          "Откройте «Иерархия метрик» под «Пространством решений». Нажмите корень и запишите бизнес-цель, например увеличить выручку от рассылок.",
          "Нажмите «Добавить метрику». Для выручки на клиента укажите формулу, единицу, желаемое направление, источник данных и окно. Например, суммируйте оплаты за 30 дней и делите на число всех клиентов, которым назначили действие, включая группу без письма.",
          "Через «Добавить дочернюю метрику» создайте ветвь для показателя, который может объяснить результат. Укажите его роль. Например, выручку измеряют в онлайн-эксперименте, а офлайн-метрику качества модели — на отложенной выборке. Функцию потерь указывают отдельно, если важно объяснить, что модель оптимизирует при обучении."
        ]
      },
      {
        "title": "Как проверить прокси",
        "paragraphs": [
          "В поле «Связь с родителем» объясните, связаны ли показатели формулой или вы предполагаете влияние. Например, долю кликов можно предложить как прокси для выручки, но клиент может нажать на письмо и ничего не купить.",
          "В поле «Как проверить связь» запишите проверку. Например, сравнить прирост выручки между случайно назначенными группами и проверить, сопровождается ли рост кликов ростом выручки. Отдельно можно отслеживать долю отписок."
        ]
      },
      {
        "title": "Как дополнить и сохранить дерево",
        "paragraphs": [
          "Откройте «Предложить метрики с AI», выберите бизнес-цель или метрику и нажмите «Запросить метрики». Модель получает текущее дерево целиком, бизнес-цель, выбранную ветвь и текст запроса. Если для предложения нужны ответы из пространства проблем или выводы из кейса, добавьте их в запрос.",
          "Проверьте определения и нажмите «Добавить в дерево». В карточке можно перенести ветвь к другому родителю. Нажмите «Сохранить», чтобы выбрать эту иерархию при сборке документа. В «Деревья метрик» доступны библиотека, экспорт и импорт JSON."
        ]
      }
    ]
  },
  {
    "id": "design-docs",
    "title": "Дизайн-документы",
    "group": "Проектирование ML",
    "intro": "Заполните шесть разделов в визуальном редакторе или соберите черновик из сохранённых материалов. Панель над текстом добавляет заголовки, списки, ссылки, таблицы и код. Документ сохраняется в Markdown. На примере рассылок в документе должны встретиться правило выбора письма и способ проверить его эффект.",
    "sections": [
      {
        "title": "Что записать в раздел «Датасет»",
        "paragraphs": [
          "В пустом поле «Датасет» нажмите «Вставить структуру». Вы получите четыре подраздела — ETL, фильтрацию, генерацию признаков и разметку. Подсказки раскрываются над полем. Например, для рассылок укажите, что один пример — клиент в момент назначения действия, а метка покупки становится известна после окончания окна наблюдения.",
          "Для прогноза продаж единицей наблюдения может быть товар в магазине за день. Продажи берутся из транзакций, а остаток помогает понять, был ли товар доступен. Для поиска изображений единицей может быть пара «запрос — фото». Клики и экспертные оценки релевантности происходят из разных источников и могут использоваться для разных целей.",
          "В подразделе «Генерация признаков» опишите входы модели. Например, историю покупок можно вычислить на дату назначения, а сумму последующей покупки использовать для оценки результата."
        ]
      },
      {
        "title": "Как заполнить раздел «Валидация»",
        "paragraphs": [
          "После «Датасета» раскройте памятку, чтобы выбрать схему проверки. Кнопка «Вставить структуру» добавит четыре заголовка в пустой раздел. Для рассылок опишите, как выбрать правило на валидационной части и сравнить его с базовым на независимых клиентах."
        ]
      },
      {
        "title": "Как выбрать источники",
        "paragraphs": [],
        "steps": [
          "В дизайн-документе нажмите «Связать этапы задачи». Выберите дерево проблем, отметьте его кейсы и выберите иерархию метрик. Нажмите «Применить связи», затем «Сохранить». Шаги в шапке будут открывать связанные материалы. При следующей сборке черновика редактор подставит этот выбор.",
          "В поле «Иерархия метрик» выберите сохранённое дерево. Чтобы собрать черновик только по метрикам, оставьте у дерева проблем «Не использовать». Иерархию также можно добавить к вопросам и кейсам.",
          "Нажмите «Подготовить предложение». В разделе «Метрики» проверьте критерий успеха, данные, окно измерения и способ проверки прокси. Недостающие условия стоит вынести в открытые вопросы."
        ]
      },
      {
        "title": "Как применить и проверить черновик",
        "paragraphs": [
          "В предпросмотре пустые разделы отмечены для заполнения. Для замены уже написанного раздела сравните свой текст с предложением и отметьте его сами. Нажмите «Применить выбранные разделы», затем «Сохранить».",
          "Под принятым текстом раскройте «Источники раздела». Здесь можно проверить ответы, выбранные кейсы, версию иерархии и определения использованных метрик. Если источник изменится, редактор укажет разделы для пересмотра. Вы сами решаете, когда пересобрать черновик."
        ]
      },
      {
        "title": "Какие вопросы задаёт ревью",
        "paragraphs": [
          "Нажмите «Провести ревью» после заполнения хотя бы одного раздела. Модель читает текущий текст, включая несохранённые правки, и сверяет его с определениями метрик, сохранёнными в источниках разделов. По спорному месту она приводит цитату, пояснение и вопрос автору.",
          "Например, если успех рассылки определён через выручку, а проверка описывает только клики, в документе остаётся вопрос о связи между ними. Ответ и изменения в текст вносит автор."
        ]
      },
      {
        "title": "Как передать документ дальше",
        "paragraphs": [
          "«Добавить в AI Chat» прикрепляет сохранённую версию документа. В чате кнопка «Прочитать» открывает вложение. После сохранения правок нажмите «Обновить», чтобы передать новую версию. «Убрать» отсоединяет документ от чата. Чтобы обсудить реализацию или построить схему, отправьте отдельный запрос.",
          "Для передачи документа файлом нажмите «Экспорт JSON». Чтобы открыть такой файл в Архитекторе, перейдите в «Мои документы» и выберите «Импорт JSON»."
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
          "Вложения передаются настроенной модели. Доступный объём контекста зависит от модели и провайдера."
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
          "Запускайте приложение через run_local.py: зависимости Python устанавливаются автоматически. Для загрузок нужна сеть; локальная работа с CSV не требует ключей.",
          "Если модель AI не отвечает, проверьте адрес API, название модели и ключ. Для CPU-обучения установите requirements-ml.txt. Сохраняйте важные данные перед обновлением приложения."
        ]
      }
    ]
  }
];

  const groups = ['Начало работы', 'Проектирование ML', 'Данные', 'Блоки и связи', 'Запуски и результаты', 'AI и подключения', 'Совместная работа', 'Практика', 'Решение проблем'];
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
  const searchable = article => [article.title, article.group, article.intro, ...article.sections.flatMap(section => [section.title, ...section.paragraphs, ...(section.steps || []), section.code || ''])].join(' ');
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