## Adding More Translations

To add more translations to the project, follow these steps:

### 1. Install Babel

Ensure that the Babel library is installed. You can install it using the following command:

```bash
pip install Babel
```

### 2. Extract Messages
First cd into the tina4_python directory
    
    ```bash
    cd tina4_python
    ```

Use the following command to extract messages from your Python files and generate a POT file:

```bash
pybabel extract -o messages.pot .
```

This will create a `messages.pot` file in the tina4_python directory.

### 3. Initialize Translations

Initialize translations for a new language. Replace `fr` with the language code of your choice:

```bash
pybabel init -i messages.pot -d translations -l fr
```

This will create a new directory `fr` under the `translations` directory with a `.po` file for the French language.

### 4. Edit Translation Files

Edit the generated `.po` file (`translations/fr/LC_MESSAGES/messages.po`) using a text editor. Translate the messages within the `msgstr` fields.

### 5. Compile Translations

After making translations, compile them into machine-readable `.mo` files:

```bash
pybabel compile -d translations
```

### 6. Update Translations

If you make changes to the source code and need to update translations, use the following commands:

```bash
pybabel extract -F babel.cfg -o messages.pot .
pybabel update -i messages.pot -d translations
```

### 7. Run the Application in a Different Language

Run your Tina4_Python application with the desired language. For example, to run it in French:

```bash
poetry run main.py fr
```

Replace `fr` with the language code you've added translations for.
