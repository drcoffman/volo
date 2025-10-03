# Terminal 1:
``` bash 
ollama serve ```

in same terminal: 
``` bash

cd code/volo
npm start
```

# Terminal 2
``` bash 
cd code/volo
source venv/bin/activate
python3 flaskserver.py
```
the main page is localhost:3000
the zim selector page is http://localhost:1255/zim


NPM, in the context of Node.js, stands for Node Package Manager.
It serves as the default package manager for Node.js, providing a way to install, manage, and share JavaScript packages and their dependencies. This includes a vast online registry of open-source JavaScript projects and a command-line utility for interacting with this registry and managing packages within your own projects.