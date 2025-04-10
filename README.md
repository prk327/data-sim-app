# My Package

A Python package for data simulation and Vertica database operations.

## Installation

```bash
pip install .
```
## Development
Here's how to connect two Docker containers (Vertica and the Python container) by creating and linking them to a custom network:

Steps to Create and Link Docker Networks for Communication Between Two Containers
1. Create a Custom Docker Network
First, create a custom bridge network so that the containers can communicate with each other.

```bash
docker network create vertica-network
```
This command will create a network named vertica-network.

2. Attach Vertica Container to the Custom Network
Next, you need to attach the already running Vertica container to the custom network you just created. You can do this using the docker network connect command.

First, identify your Vertica container's name or ID by running:

```bash
docker ps
```
Then, connect the Vertica container to the vertica-network:

```bash
docker network connect vertica-network <vertica_container_name_or_id>
```
Replace ```<vertica_container_name_or_id>``` with the actual name or ID of your Vertica container. This allows the Vertica container to communicate with other containers on the same network.

3. Run the Python Container on the Same Network
Now, when you run your Python container, ensure it’s connected to the same custom network. Here's how to run the Python container and attach it to the same network as Vertica:

```bash
docker run -d --name python-script-container --network vertica-network my-python-image
```
```--network vertica-network:``` This ensures the Python container joins the vertica-network, allowing it to communicate with Vertica.
Replace my-python-image with the name of the image you're using to run the Python script.

4. For Docker Compose add the below in service:

    ```
    services:
        jupyter:
        ...
            networks:
                - vertica-network
    
    networks:
        vertica-network:
            external: true               # Use an external network if Vertica is outside Compose
    ```

5. To connect to vertica from python script, inspect

```bash
docker inspect vertica-network
```

look for Containers key and find the name that you can use to connect to vertica under host

Something like below 
```
"Containers": {
            ".....": {
                "Name": "vertica-ce",
                "EndpointID": "...",
                "MacAddress": "...",
                "IPv4Address": ".../...",
                "IPv6Address": ""
            }}
```

To Test if everythinmg is woking fine:

Create 3 tables:

1. User:
```SQL
CREATE TABLE omniq.users (
    user_id INT PRIMARY KEY,          
    username VARCHAR(100),      
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

2. Product:
```SQL
CREATE TABLE omniq.products ( 
    products_id INT,
    product_name VARCHAR(100)
);
```

3. Orders:
```SQL
CREATE TABLE omniq.orders (
    order_id INT PRIMARY KEY,
    user_id INT,
    products_id INT,
    order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    amount DECIMAL(10,2)
);
```

Create table file in table folder

### User Table
```yaml
table_name: USERS
primary_key: UNIQUE_ID
columns:
- NAME
- TIME_STAMP
```

### Product Table
```yaml
table_name: PRODUCTS
primary_key: PRODUCTS_ID
columns:
- PRODUCT_NAME
```

### Orders Table
```yaml
table_name: ORDERS
primary_key: ORDERS_ID
columns:
- UNIQUE_ID
- PRODUCTS_ID
- ORDER_DATE
- AMOUNT
```

Execute the data_simulator.py,
After running the script, check if all three tables have data,
Also, validate if the data is making sense by running below
Query: It will show for each user and product there must be some orders

```SQL
select
	o.order_id,
	u.NAME,
	p.product_name,
	o.order_date,
	o.amount
from
	omniq.orders o
left join omniq.users u on o.UNIQUE_ID = u.UNIQUE_ID
left join omniq.products p on o.products_id = p.products_id
```
