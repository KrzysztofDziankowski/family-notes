# Family Entries REST API — Implementation Plan

## Overview

Dodać tokenowy, rodzinny i wyłącznie odczytowy endpoint `GET /api/automation/entries/`. Endpoint zwróci pełne domenowe dane wpisów, zapewni stabilną paginację `limit + offset` oraz opcjonalne filtrowanie po datach.

## Current State Analysis

- `automation_token_required` uwierzytelnia Bearer token, odrzuca tokeny nieważne, cofnięte i wygasłe oraz nieaktywnego właściciela lub rodzinę.
- Poprawne uwierzytelnienie udostępnia `request.automation_membership`, z którego należy wyprowadzać rodzinę.
- `Entry` nie ma domyślnego sortowania, a reguły list HTML dzielą wpisy na sekcje i pomijają niektóre rodzaje, więc nie są kontraktem dla „wszystkich wpisów”.
- API korzysta ze zwykłych widoków Django i `JsonResponse`.
- Roadmapa `MS-01` świadomie zastępuje wcześniejszy zakaz odczytu danych przez token, ale wyłącznie dla tego endpointu.

## Desired End State

Żądanie z aktywnym tokenem rodzica zwraca wyłącznie wpisy rodziny właściciela tokenu. Klient może pobierać kolejne strony, ograniczać wpisy do włącznie traktowanego zakresu dat oraz opcjonalnie dołączać wpisy bez daty.

### Public API

`GET /api/automation/entries/` z nagłówkiem `Authorization: Bearer <token>`.

Obsługiwane parametry:

- `limit`: liczba całkowita `1..500`, domyślnie `100`.
- `offset`: nieujemna liczba całkowita, domyślnie `0`.
- `date_from`: opcjonalna data ISO `YYYY-MM-DD`, granica włącznie.
- `date_to`: opcjonalna data ISO `YYYY-MM-DD`, granica włącznie.
- `include_undated`: opcjonalnie `true` albo `false` bez rozróżniania wielkości liter (`True`, `FALSE` są poprawne; `1`, `0`, `yes` i pusta wartość to `400`); domyślnie `true` bez granic dat i `false` przy co najmniej jednej granicy.

Bez `date_from` i `date_to` zwracane są wpisy datowane i bez daty, a jawne `include_undated=false` ogranicza wynik do wszystkich wpisów datowanych. Podanie co najmniej jednej granicy wyklucza wpisy bez daty, chyba że `include_undated=true`; każda granica może wystąpić samodzielnie. `date_from > date_to` jest błędem. Poprawny składniowo, ale nieistniejący dzień (np. `2026-02-30`) jest błędem `400`, a nie wyjątkiem `500`. Nieznane parametry są ignorowane dla przyszłej kompatybilności. Wyniki są sortowane przez `created_at ASC, id ASC`, więc nowe wpisy (także tworzone w tle przez S-05) trafiają na koniec i nie przesuwają wcześniejszych stron; `count` oznacza liczbę wszystkich rekordów po filtrowaniu, przed paginacją. Strony nie są snapshotem: usunięcie wpisu między żądaniami może przesunąć kolejne strony, co dokumentacja opisuje wraz z zaleceniem deduplikacji po `id`.

Odpowiedź `200` ma envelope `{ "count": N, "limit": N, "offset": N, "results": [...] }`. Rekord zawiera `id`, `entry_type`, `content`, `date`, `time`, `assigned_member`, `school_item`, `source`, `created_at` i `updated_at`. Daty, czas i znaczniki czasu są ciągami ISO 8601; brak osoby, daty, czasu lub elementu szkolnego jest reprezentowany przez `null`. `assigned_member` zawiera wyłącznie `display_name`.

Błędny typ, zakres lub format parametru zwraca `400 {"error":"invalid_query"}`. Błąd tokenu zachowuje istniejące `401 {"error":"invalid_token"}` i `WWW-Authenticate: Bearer`. Metoda inna niż GET zwraca 405.

### Key Discoveries

- `family_access/automation.py:26-73` udostępnia gotową, fail-closed granicę tokenową i ustawia `request.automation_membership`.
- `entries/services.py:109-118` pokazuje istniejący wzorzec rodzinnego querysetu z `select_related("assigned_member")`.
- `entries/listing.py:58-103` zawiera reguły właściwe tylko dla UI, których API nie powinno dziedziczyć.
- `entries/models.py:16-78` definiuje dozwolone pola domenowe i brak modelowego sortowania.

## What We're NOT Doing

- Nie dodajemy endpointu `GET /api/automation/entries/<id>/` ani metod mutujących.
- Nie udostępniamy `family_id`, `created_by`, `submission_key` ani danych tokenu.
- Nie dodajemy filtrów po osobie lub rodzaju, API członków, nowych scope’ów tokenów ani UI.
- Nie zmieniamy modelu `Entry`, schematu bazy ani sposobu wydawania tokenów.
- Nie konsolidujemy modułów URL, jeśli równoległy S-05 jeszcze tego nie zrobił.
- Nie odtwarzamy sekcji ani filtrów listy HTML.

## Implementation Approach

Widok API użyje istniejącego dekoratora `automation_token_required`. Rodzina zostanie pobrana wyłącznie z `request.automation_membership`; żaden identyfikator rodziny od klienta nie będzie akceptowany. Osobna funkcja odczytu przygotuje rodzinny queryset, filtry i stabilne sortowanie, a serializer przekształci rekordy do jawnie dozwolonego kontraktu.

## Phase 1: Kontrakt odczytu

### Overview

Zbudować niezależny od HTTP kontrakt filtrowania, paginacji i serializacji wpisów.

### Changes Required:

#### 1. Warstwa odczytu wpisów

**File**: `entries/services.py`

**Intent**: Zapewnić jeden rodzinny odczyt używany przez endpoint, bez korzystania z filtrów przeznaczonych dla HTML.

**Contract**: Nowa funkcja (np. `automation_family_entries(membership, date_from, date_to, include_undated)`) buduje na istniejącym `_family_entries(membership)`, który już stosuje `scope_queryset_to_family` i `select_related("assigned_member")`; nie tworzymy drugiego rodzinnego querysetu. Queryset zawsze filtruje po uwierzytelnionym `membership.family`, dołącza `assigned_member`, obsługuje włączne granice dat oraz wpisy bez daty i kończy stabilnym `order_by("created_at", "id")`.

#### 2. Parser parametrów i serializer

**File**: `entries/api_views.py`

**Intent**: Oddzielić walidację publicznych parametrów od składania odpowiedzi.

**Contract**: Parametry i format odpowiedzi odpowiadają sekcji Public API. Docstring modułu `api_views.py` zostaje rozszerzony z samego intake’u na oba endpointy automatyzacji (plik jest równolegle edytowany przez S-05 — zmiany ograniczyć do dopisania nowego kodu). Serializer używa jawnej listy pól, normalizuje brak `school_item` do `null` i zwraca wyłącznie `display_name` przypisanej osoby.

### Success Criteria:

#### Automated Verification:

- Testy parsera potwierdzają wartości domyślne, granice `limit`, nieujemny `offset`, format ISO dat i nieistniejący dzień (`2026-02-30`), boolean bez rozróżniania wielkości liter z odrzuceniem `1`/`0`/pustej wartości oraz odwrócony zakres.
- Testy filtrowania potwierdzają obie włączne granice, granice jednostronne i zachowanie `include_undated`, także jawne `false` bez granic dat (tylko wpisy datowane).
- Testy serializacji potwierdzają pola domenowe, wartości `null`, nieaktywną historyczną osobę oraz brak pól wewnętrznych.
- Testy kolejności potwierdzają `created_at ASC, id ASC`, także przy remisie czasu, oraz że wpis dodany między stronami nie powtarza się na kolejnej stronie.

**Verification command**: `uv run python manage.py test entries.tests.test_entries_api`

---

## Phase 2: Endpoint i bezpieczeństwo

### Overview

Udostępnić kolekcję pod istniejącym prefiksem automatyzacji i zamknąć pełną macierz dostępu.

### Changes Required:

#### 1. Widok i routing

**Files**: `entries/api_views.py`, `entries/api_urls.py`

**Intent**: Dodać wyłącznie odczytowy endpoint zgodny z istniejącym stylem API.

**Contract**: `GET /api/automation/entries/` używa `@require_GET` na zewnątrz i `@automation_token_required` wewnątrz, dzięki czemu błędna metoda zwraca 405 przed uwierzytelnieniem. Widok zwraca envelope `{count, limit, offset, results}`.

#### 2. Testy integracyjne API

**File**: `entries/tests/test_entries_api.py` (wspólny z testami fazy 1)

**Intent**: Udowodnić poprawność kontraktu, izolację rodzin i brak możliwości mutacji.

**Contract**: Testy obejmują własne wpisy, wpisy bez daty, wszystkie typy i źródła, obcą rodzinę jako sentinel, pustą stronę, offset poza końcem oraz pełny kontrakt 400/401/405.

### Success Criteria:

#### Automated Verification:

- Aktywny token rodzica otrzymuje wyłącznie wpisy swojej rodziny.
- Brakujący, błędny, cofnięty i wygasły token oraz nieaktywny rodzic, użytkownik lub rodzina otrzymują istniejący kontrakt 401.
- Wpis obcej rodziny nigdy nie pojawia się w `results` ani nie zwiększa `count`.
- POST, PUT, PATCH i DELETE nie zmieniają danych i zwracają 405.
- Filtry, paginacja, kolejność i envelope zachowują uzgodniony kontrakt.
- Istniejące testy tokenu, intake’u, zarządzania wpisami i widoku dziecka pozostają zielone.

#### Manual Verification:

- Lokalny `curl` z aktywnym tokenem zwraca oczekiwane wpisy rodziny.
- Ten sam `curl` po cofnięciu tokenu natychmiast zwraca 401.

**Verification commands**: `uv run python manage.py test entries.tests.test_entries_api` (2.1–2.5) oraz `uv run python manage.py test family_access entries.tests.test_notification_intake entries.tests.test_manage_views entries.tests.test_manage_access entries.tests.test_manage_states entries.tests.test_child_views entries.tests.test_child_entries entries.tests.test_child_states_view` (2.6).

**Implementation Note**: Po testach automatycznych zatrzymać fazę do potwierdzenia ręcznej próby aktywnego i cofniętego tokenu.

---

## Phase 3: Dokumentacja i akceptacja

### Overview

Udokumentować publiczny kontrakt oraz typowe pobieranie wpisów od dziś do czterech tygodni naprzód.

### Changes Required:

#### 1. Dokumentacja operatora i klienta

**File**: `README.md`

**Intent**: Umieścić gotowe przykłady `curl`, opis parametrów i bezpieczne zasady obchodzenia się z tokenem.

**Contract**: Dokumentacja pokazuje pobranie całej pierwszej strony oraz zakres `date_from`–`date_to`, opcjonalne `include_undated=true`, przechodzenie po `offset`, znaczenie `count` oraz to, że strony nie są snapshotem (usunięcia mogą je przesunąć; klient deduplikuje po `id`). Token pozostaje placeholderem i nie trafia do historii repozytorium ani logów. Notatka operatora informuje, że od S-06 każdy aktywny token rodzica — także wydany wcześniej wyłącznie do intake’u — odczytuje wszystkie wpisy rodziny, więc tokeny, których automatyzacja nie powinna mieć tego dostępu, należy cofnąć.

#### 2. Weryfikacja wydania

**Intent**: Potwierdzić brak zmian schematu i regresji całej aplikacji.

**Contract**: Uruchomić testy Django, system checks i kontrolę brakujących migracji.

### Success Criteria:

#### Automated Verification:

- `uv run python manage.py test` przechodzi.
- `uv run python manage.py check` przechodzi.
- `uv run python manage.py makemigrations --check --dry-run` nie wykrywa zmian modelu.
- Przykłady i opis endpointu są obecne w `README.md`.

#### Manual Verification:

- Produkcyjny lub lokalny `curl` dla jawnego zakresu dziś → +28 dni zwraca tylko wpisy datowane w tym zakresie.
- Dodanie `include_undated=true` do tego samego zakresu dołącza wpisy bez daty.
- Odpowiedź i logi nie ujawniają tokenu, nagłówka Authorization ani danych innej rodziny.

## Testing Strategy

### Unit Tests:

- Walidacja każdej wartości granicznej parametrów.
- Włączne filtrowanie dat oraz opcjonalne wpisy bez daty.
- Stabilna kolejność i normalizacja pól JSON.
- Serializacja nieaktywnej historycznej osoby.

### Integration Tests:

- Pełna macierz poprawnego i błędnego tokenu.
- Izolacja dwóch rodzin z jednoznacznym sentinelem.
- Brak mutacji dla wszystkich niedozwolonych metod.
- `count` liczony po filtrach, ale przed `limit` i `offset`.
- Brak regresji istniejących endpointów `ping` i `notifications`.

### Manual Testing Steps:

1. Wydać lokalny token rodzica i pobrać pierwszą stronę.
2. Pobrać jawny zakres dat odpowiadający dziś → +28 dni.
3. Powtórzyć z `include_undated=true`.
4. Cofnąć token i potwierdzić natychmiastowe 401.
5. Sprawdzić, że odpowiedź nie zawiera pól wewnętrznych ani sentinela obcej rodziny.

## Performance Considerations

Queryset filtruje rodzinę przed `count` i slicingiem oraz używa `select_related("assigned_member")`, aby uniknąć zapytań N+1. Limit 500 stanowi twarde ograniczenie rozmiaru pojedynczej odpowiedzi. Nie dodajemy nowego indeksu bez dowodu z pomiaru; bieżąca skala jest mała, a istnieje indeks rodzina–data.

## Migration Notes

Brak migracji i transformacji danych. Wycofanie funkcji polega na usunięciu route’u i kodu odczytu; nie pozostawia zmian w bazie.

## References

- `context/foundation/roadmap.md` — owner-directed `MS-01` i S-06.
- `family_access/automation.py` — istniejąca granica tokenowa.
- `entries/models.py` — model i pola wpisu.
- `entries/services.py` — rodzinne query sety.
- `entries/listing.py` — reguły list HTML, których API nie dziedziczy.
- `context/archive/2026-09-27-automation-token-access/plan.md` — kontrakt tokenu.
- `context/archive/2026-09-28-parent-family-entry-management/plan.md` — zasady izolacji wpisów.

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Kontrakt odczytu

#### Automated

- [x] 1.1 Testy parsera potwierdzają wartości domyślne, granice `limit`, nieujemny `offset`, format ISO dat i nieistniejący dzień (`2026-02-30`), boolean bez rozróżniania wielkości liter z odrzuceniem `1`/`0`/pustej wartości oraz odwrócony zakres. — e17cfb7
- [x] 1.2 Testy filtrowania potwierdzają obie włączne granice, granice jednostronne i zachowanie `include_undated`, także jawne `false` bez granic dat (tylko wpisy datowane). — e17cfb7
- [x] 1.3 Testy serializacji potwierdzają pola domenowe, wartości `null`, nieaktywną historyczną osobę oraz brak pól wewnętrznych. — e17cfb7
- [x] 1.4 Testy kolejności potwierdzają `created_at ASC, id ASC`, także przy remisie czasu, oraz że wpis dodany między stronami nie powtarza się na kolejnej stronie. — e17cfb7

### Phase 2: Endpoint i bezpieczeństwo

#### Automated

- [x] 2.1 Aktywny token rodzica otrzymuje wyłącznie wpisy swojej rodziny.
- [x] 2.2 Brakujący, błędny, cofnięty i wygasły token oraz nieaktywny rodzic, użytkownik lub rodzina otrzymują istniejący kontrakt 401.
- [x] 2.3 Wpis obcej rodziny nigdy nie pojawia się w `results` ani nie zwiększa `count`.
- [x] 2.4 POST, PUT, PATCH i DELETE nie zmieniają danych i zwracają 405.
- [x] 2.5 Filtry, paginacja, kolejność i envelope zachowują uzgodniony kontrakt.
- [x] 2.6 Istniejące testy tokenu, intake’u, zarządzania wpisami i widoku dziecka pozostają zielone.

#### Manual

- [ ] 2.7 Lokalny `curl` z aktywnym tokenem zwraca oczekiwane wpisy rodziny.
- [ ] 2.8 Ten sam `curl` po cofnięciu tokenu natychmiast zwraca 401.

### Phase 3: Dokumentacja i akceptacja

#### Automated

- [ ] 3.1 `uv run python manage.py test` przechodzi.
- [ ] 3.2 `uv run python manage.py check` przechodzi.
- [ ] 3.3 `uv run python manage.py makemigrations --check --dry-run` nie wykrywa zmian modelu.
- [ ] 3.4 Przykłady i opis endpointu są obecne w `README.md`.

#### Manual

- [ ] 3.5 Produkcyjny lub lokalny `curl` dla jawnego zakresu dziś → +28 dni zwraca tylko wpisy datowane w tym zakresie.
- [ ] 3.6 Dodanie `include_undated=true` do tego samego zakresu dołącza wpisy bez daty.
- [ ] 3.7 Odpowiedź i logi nie ujawniają tokenu, nagłówka Authorization ani danych innej rodziny.
